"""Function-authenticated cached reads and a managed-identity scheduled collector."""
from contextlib import ExitStack
import logging
import os
import re

import azure.functions as func
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from azure.storage.blob import BlobServiceClient, ContentSettings

from collect import ContractError, MAX_BYTES
from pipeline import CollectionFailed, DATASET, execute, dataset_content

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def azure_url(name, suffix):
    value = os.environ[name]
    if not re.fullmatch(r"https://[a-z0-9-]+\." + re.escape(suffix) + r"/?", value):
        raise ContractError("Expected a standard HTTPS Azure service endpoint")
    return value.rstrip("/")


@app.function_name(name="dataset")
@app.route(route="dataset", methods=["GET"], auth_level=func.AuthLevel.FUNCTION,
           trigger_arg_name="request")
def dataset_snapshot(request: func.HttpRequest) -> func.HttpResponse:
    try:
        with ExitStack() as stack:
            credential = stack.enter_context(ManagedIdentityCredential())
            service = stack.enter_context(BlobServiceClient(
                account_url=azure_url("DATA_BLOB_ACCOUNT_URL", "blob.core.windows.net"),
                credential=credential, logging_enable=False))
            blob = service.get_blob_client(os.environ["DATA_CONTAINER"], DATASET)
            content = blob.download_blob(offset=0, length=MAX_BYTES + 1,
                                         logging_enable=False).readall()
            return func.HttpResponse(dataset_content(content), mimetype="application/json",
                                     headers={"Cache-Control": "private, no-store",
                                              "X-Content-Type-Options": "nosniff"})
    except (AzureError, ContractError, ValueError, KeyError, TypeError, OSError) as error:
        logging.error("snapshot_read_failed error_type=%s", type(error).__name__)
        return func.HttpResponse("Validated REAL snapshot unavailable", status_code=503,
                                 headers={"Cache-Control": "private, no-store"})


@app.function_name(name="collect_metrics")
@app.timer_trigger(schedule="%METRICS_SCHEDULE%", arg_name="timer",
                   run_on_startup=False, use_monitor=True)
def collect_metrics(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("collection_timer_past_due")
    try:
        with ExitStack() as stack:
            credential = stack.enter_context(ManagedIdentityCredential())
            secrets = stack.enter_context(SecretClient(
                vault_url=azure_url("KEY_VAULT_URL", "vault.azure.net"),
                credential=credential, logging_enable=False))
            service = stack.enter_context(BlobServiceClient(
                account_url=azure_url("DATA_BLOB_ACCOUNT_URL", "blob.core.windows.net"),
                credential=credential, logging_enable=False))
            container = service.get_container_client(os.environ["DATA_CONTAINER"])

            def read(name):
                try:
                    return container.get_blob_client(name).download_blob(
                        offset=0, length=8193, logging_enable=False).readall()
                except ResourceNotFoundError:
                    return None

            def write(name, payload, metadata):
                container.get_blob_client(name).upload_blob(
                    payload, overwrite=True, metadata=metadata,
                    content_settings=ContentSettings(content_type="application/json",
                                                     cache_control="private, no-store"),
                    logging_enable=False)

            execute(os.environ, lambda name: secrets.get_secret(name, logging_enable=False).value,
                    read, write)
    except CollectionFailed as error:
        logging.error("collection_failed stage=%s error_type=%s committed=%s",
                      error.stage, error.error_type, error.dataset_committed)
        raise RuntimeError("Scheduled collection failed; last validated Blob remains the data source") from None
    except (AzureError, ContractError, ValueError, KeyError, TypeError, OSError) as error:
        logging.error("cloud_connection_failed error_type=%s", type(error).__name__)
        raise RuntimeError("Cloud connection or configuration failed; check monitoring") from None
