"""Private bootstrap adapter over the existing protected Mesh Chat service.

No renderer/IPC command invokes this factory. Platform authentication must supply
the current caller grant before the component becomes a public host interface.
"""

from .session import ApiFailure, CoreSession, Ports, ProfileObservation
from .service_invitations import ServiceInvitations
from .service_lifecycle import ServiceLifecycle
from .service_workspace import ServiceWorkspace
from .service_workspace_admin import ServiceWorkspaceAdmin
from .service_application_runtime import ServiceApplicationRuntime
from .service_workspace_timeline import ServiceWorkspaceTimeline
from .service_messages import ServiceMessages
from .service_pairing import ServicePairing
from .service_recovery import ServiceRecovery
from .service_diagnostics import ServiceDiagnostics
from .service_intent import ServiceIntent
from .application import ServiceApplication
from .service_calls import ServiceCallSettings
from .service_groups import ServiceGroups
from .service_reactions import ServiceReactions
from .service_settings import ServiceNetworkSettings
from .service_drafts import ServiceDrafts
from .service_relationship import ServiceRelationship
from .wire import FramedSession


class ServiceObservations:
    def __init__(self, service):
        self._service = service

    def profile(self, internal_profile):
        if internal_profile != "local":
            raise ApiFailure("forbidden")
        service = self._service
        if service._identity is None:
            raise ApiFailure("locked")
        profile = service._require_profile()
        runtime = service._connection_runtime
        connections = runtime.snapshots() if runtime is not None else {}
        return ProfileObservation(profile["display_name"], profile["destination_hash"], connections)


def bind_service_session(service, authenticated_grant):
    """Trusted host entry point, never a client-supplied identity or grant."""
    def current_grant():
        return None if service._shutdown.is_set() else authenticated_grant()

    with service._dispatch_lock:
        handle_key = bytes.fromhex(service.store.opaque_id("core-api-handle-key", "v1"))
        messages = ServiceMessages(service)
        recovery = ServiceRecovery(service, messages) if hasattr(service, "_message_journal") else None
        received = recovery if hasattr(service, "_received_messages") else None
        intent = ServiceIntent(service) if hasattr(service, "reconnect_start") else None
        relationship = (ServiceRelationship(service) if hasattr(service, "approve_request")
                        else None)
        pairing = ServicePairing(service) if hasattr(service, "accept_invitation") else None
        invitations = ServiceInvitations(service) if hasattr(service, "invitation") else None
        lifecycle = (ServiceLifecycle(service) if hasattr(service, "_shutdown") else None)
        workspace = (ServiceWorkspace(service)
                     if hasattr(service, "submit_workspace_join") else None)
        workspace_admin = (ServiceWorkspaceAdmin(service)
                           if hasattr(service, "approve_workspace_join") else None)
        workspace_timeline = (ServiceWorkspaceTimeline(service, service.store)
                              if hasattr(service, "list_workspace_threads") else None)
        runtime = (ServiceApplicationRuntime(service)
                   if hasattr(service, "background_availability_status") else None)
        ports = Ports(messages=messages, recovery=recovery,
                      diagnostics=ServiceDiagnostics(service, messages), received=received,
                      intent=intent, relationship=relationship, pairing=pairing,
                      invitations=invitations, lifecycle=lifecycle, workspace=workspace,
                      workspace_admin=workspace_admin,
                      workspace_timeline=workspace_timeline,
                      runtime=runtime,
                      application=ServiceApplication(service),
                      drafts=ServiceDrafts(service),
                      calls=ServiceCallSettings(service),
                      settings=ServiceNetworkSettings(service),
                      reactions=ServiceReactions(service),
                      groups=ServiceGroups(service))
        return CoreSession(current_grant, ServiceObservations(service), handle_key=handle_key,
                           transaction=service._dispatch_lock, ports=ports)


def bind_service_stream(service, authenticated_grant):
    """Private host binding; raw frames can never select the grant callback."""
    return FramedSession(bind_service_session(service, authenticated_grant))
