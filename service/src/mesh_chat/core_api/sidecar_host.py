"""Host-owned Core API endpoint for the packaged desktop sidecar.

The sidecar starts this only when the trusted launcher supplies a pipe name and
the exact client image. JSON initialization cannot select either fact.
"""

from .host import OWNER_PERMISSIONS
from .pipe_endpoint import PipeConfig, PipeEndpoint

CALLER = "mesh-chat-application"


def start(service, *, pipe_name, client_image):
    """Serve owner-scope Core API operations on one app-owned named pipe."""
    if not isinstance(pipe_name, str) or not pipe_name:
        raise ValueError("Core API pipe name is required")
    if not isinstance(client_image, str) or not client_image:
        raise ValueError("Core API client image is required")
    config = PipeConfig(
        caller=CALLER,
        permissions=tuple(sorted(OWNER_PERMISSIONS | {"profile_owner"})),
        allowed_images=(client_image,),
        max_clients=2,
        idle_timeout=300.0,
        scope="owner",
        private_native=True,
        private_profile_bootstrap=True,
        private_composer_legacy=True,
    )
    endpoint = PipeEndpoint(pipe_name, config)
    endpoint.start(service)
    return endpoint
