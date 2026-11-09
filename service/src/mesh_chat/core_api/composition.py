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
from .native_commands import ServiceNativeCommands
from .profile_bootstrap import ServiceProfileBootstrap
from .service_calls import ServiceCallSettings
from .service_groups import ServiceGroups
from .service_reactions import ServiceReactions
from .service_settings import ServiceNetworkSettings
from .service_drafts import ServiceDrafts
from .service_composer import ServiceComposer
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


def bind_service_session(service, authenticated_grant, *, private_native=False,
                         private_profile_bootstrap=False, private_composer_legacy=False,
                         handle_key=None, call_retirement=None):
    """Trusted host entry point, never a client-supplied identity or grant."""
    if type(private_native) is not bool:
        raise ValueError("Private native binding must be a host boolean")
    if type(private_profile_bootstrap) is not bool:
        raise ValueError("Private profile bootstrap must be a host boolean")
    if type(private_composer_legacy) is not bool:
        raise ValueError("Private composer migration must be a host boolean")
    if handle_key is not None and (not isinstance(handle_key, bytes) or len(handle_key) != 32):
        raise ValueError("Private host handle key must be 32 bytes")
    def current_grant():
        return None if service._shutdown.is_set() else authenticated_grant()

    with service._dispatch_lock:
        handle_key = handle_key or bytes.fromhex(service.store.opaque_id("core-api-handle-key", "v1"))
        messages = ServiceMessages(service)
        composer = (ServiceComposer(service, messages, legacy=private_composer_legacy)
                    if hasattr(service.store, "conditional_put_and_delete") else None)
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
        calls = ServiceCallSettings(service, call_retirement)
        ports = Ports(messages=messages, composer=composer, recovery=recovery,
                      diagnostics=ServiceDiagnostics(service, messages), received=received,
                      intent=intent, relationship=relationship, pairing=pairing,
                      invitations=invitations, lifecycle=lifecycle, workspace=workspace,
                      workspace_admin=workspace_admin,
                      workspace_timeline=workspace_timeline,
                      runtime=runtime,
                      application=ServiceApplication(service),
                      native_commands=ServiceNativeCommands(service) if private_native else None,
                      profile_bootstrap=ServiceProfileBootstrap(service) if private_profile_bootstrap else None,
                      drafts=ServiceDrafts(service, legacy=private_composer_legacy),
                      calls=calls,
                      call_recovery=calls if calls.recovery_operations else None,
                      settings=ServiceNetworkSettings(service),
                      reactions=ServiceReactions(service),
                      groups=ServiceGroups(service))
        return CoreSession(current_grant, ServiceObservations(service), handle_key=handle_key,
                           transaction=service._dispatch_lock, ports=ports)


def bind_service_stream(service, authenticated_grant, *, private_native=False,
                        private_profile_bootstrap=False, private_composer_legacy=False, call_retirement=None):
    """Private host binding; raw frames can never select the grant callback."""
    return FramedSession(bind_service_session(service, authenticated_grant,
                                              private_native=private_native,
                                              private_profile_bootstrap=private_profile_bootstrap,
                                              private_composer_legacy=private_composer_legacy,
                                              call_retirement=call_retirement))
