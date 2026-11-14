"""One positive installed GUI call and independent public SDK peer scenario."""

import hashlib
import time
from uuid import uuid4


CALL_KEYS = ("stun_urls", "turn_url", "turn_username", "turn_broker_url",
             "signal_mailbox_url", "store_call_signaling")
ALTERNATE_PATHS = {"nearby_discovery": False, "lan_fallback": False, "help_route": False}


def text_for(pair_id, role, stage):
    return f"packaged-call:v1:{pair_id}:{role}:{stage}"


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Flow:
    def __init__(self, role, peer, exchange, pair_id, deadline, clock=time.monotonic):
        if role not in {"gui", "peer"}: raise ValueError("call_role")
        self.role, self.peer, self.exchange = role, peer, exchange
        self.pair_id, self.deadline, self.clock = pair_id, deadline, clock
        self.checks = {}
        self.profile = self.contact = self.pairing = self.browser = None
        self.observations = []

    def limit(self, seconds=120):
        value = min(self.deadline - 30, self.clock() + seconds)
        if value <= self.clock(): raise TimeoutError("call_total_deadline")
        return value

    def publish(self, phase, payload=None):
        self.exchange.publish(phase, {} if payload is None else payload, self.limit())

    def receive(self, phase):
        return self.exchange.receive(phase, self.limit(180))

    def wait(self, name, observe, seconds=90, interval=1):
        until = self.limit(seconds)
        while self.clock() < until:
            value = observe()
            if self.clock() >= until: break
            if value is not None: return value
            time.sleep(min(interval, max(0, until - self.clock())))
        raise TimeoutError("call_" + name)

    def request(self, operation, params=None, key=None):
        if self.clock() >= self.deadline - 30: raise TimeoutError("call_public_deadline")
        return self.peer.request(operation, params, key)

    def snapshot(self):
        return self.request("application.snapshot")

    def gui_click(self, label, scope="dialog"):
        self.peer.request("click", label=label, scope=scope)

    def gui_view(self, text=None):
        return self.peer.request("observe", **({"text": text} if text is not None else {}))

    def peer_profile(self):
        caps = self.request("runtime.capabilities")
        handles, operations = caps.get("profiles"), caps.get("operations")
        required = {"profile.create", "peer.pairing_begin", "peer.pairing_query",
                    "peer.approve", "application.snapshot", "call.ice_servers",
                    "call.media_query", "call.control", "message.enqueue", "message.query"}
        if (type(handles) is not list or len(handles) != 1 or type(handles[0]) is not str
                or type(operations) is not list or not required <= set(operations)
                or "native.command" in operations):
            raise ValueError("call_public_capabilities")
        empty = self.snapshot()
        if empty.get("profile") is not None or empty.get("contacts") or empty.get("messages"):
            raise ValueError("call_peer_not_fresh")
        self.request("profile.create", {"display_name": "Independent peer"}, str(uuid4()))
        self.profile = handles[0]
        identity = self.request("profile.query", {"profile": self.profile})
        if type(identity.get("destination")) is not str: raise ValueError("call_peer_identity")
        self.destination = identity["destination"]
        self.request("settings.update", {"profile": self.profile, "settings": ALTERNATE_PATHS})
        network = self.request("settings.query", {"profile": self.profile}).get("settings")
        if type(network) is not dict or any(network.get(key) is not False for key in ALTERNATE_PATHS):
            raise ValueError("call_peer_alternate_paths")
        settings = self.request("call.settings_query", {"profile": self.profile}).get("settings")
        if type(settings) is not dict or not all(key in settings for key in CALL_KEYS):
            raise ValueError("call_peer_settings")
        configured = {key: settings[key] for key in CALL_KEYS}
        configured.update(turn_broker_consent=True, relay_only=True)
        self.request("call.settings_update", {"profile": self.profile, "settings": configured})
        applied = self.request("call.settings_query", {"profile": self.profile}).get("settings")
        if type(applied) is not dict or applied.get("turn_broker_consent") is not True or applied.get("relay_only") is not True:
            raise ValueError("call_peer_relay")
        self.checks["fresh_peer_and_relay_consent"] = True

    def peer_pair(self):
        begun = self.request("peer.pairing_begin", {"profile": self.profile, "role": "offer",
            "allow_direct_ip_disclosure": False}, str(uuid4()))
        self.pairing = begun.get("pairing")
        if type(self.pairing) is not str or not self.pairing: raise ValueError("call_pairing_begin")
        def code():
            state = self.request("peer.pairing_query", {"profile": self.profile, "pairing": self.pairing})
            value = state.get("pairing_code")
            return value if state.get("state") == "offer_ready" and type(value) is str else None
        self.publish("offer_code", {"pairing_code": self.wait("offer_code", code)})
        self.receive("invitation_accepted")
        def pending():
            contacts = self.snapshot().get("contacts")
            if type(contacts) is not list or len(contacts) > 1: raise ValueError("call_contacts_invalid")
            return contacts[0] if contacts and contacts[0].get("trust") == "pending_request" else None
        request = self.wait("pending_request", pending)
        approved = self.request("peer.approve", {"profile": self.profile, "peer": request["core_handle"]})
        if approved.get("trust") not in {"approved", "verified"}: raise ValueError("call_approve_failed")
        self.publish("approved")
        def relationship():
            contacts = self.snapshot().get("contacts")
            if type(contacts) is not list or len(contacts) > 1: raise ValueError("call_contacts_invalid")
            return contacts[0] if contacts and contacts[0].get("trust") in {"approved", "verified"} else None
        self.contact = self.wait("relationship", relationship)
        def transferred():
            state = self.request("peer.pairing_query", {"profile": self.profile, "pairing": self.pairing})
            return state if state.get("state") == "transferred" else None
        self.wait("transfer", transferred)
        cancelled = self.request("peer.pairing_cancel", {"profile": self.profile,
                                  "pairing": self.pairing}, str(uuid4()))
        if cancelled.get("state") != "transferred" or cancelled.get("pairing_code") is not None:
            raise ValueError("call_pairing_retirement")
        remote = self.contact.get("destination_hash")
        if type(remote) is not str or remote == self.destination:
            raise ValueError("call_profile_separation")
        self.checks["peer_destination_sha256"] = digest(self.destination)
        self.checks["gui_destination_sha256"] = digest(remote)
        self.checks["signed_pair_and_explicit_approval"] = True

    def gui_pair(self):
        code = self.receive("offer_code")["pairing_code"]
        self.gui_click("Join with WebRTC", "page")
        self.peer.request("fill", label="Display name", value="Installed GUI", scope="page")
        self.gui_click("Create profile and continue", "page")
        self.wait("onboarding_dialog", lambda: True if self.gui_view()["dialogTitle"] == "Connect with WebRTC" else None)
        self.wait("relay_option", lambda: True if self.gui_view()["relayOption"] else None,
                  seconds=30)
        self.gui_click("Use the relay")
        self.wait("relay_consent", lambda: True if not self.gui_view()["relayPanelVisible"] else None)
        self.checks["gui_relay_consent"] = True
        self.gui_click("Join with WebRTC")
        self.peer.request("fill", label="Paste the signed WebRTC offer or mailbox code", value=code, scope="dialog")
        self.gui_click("Review and create answer")
        self.wait("contact_preview", lambda: True if self.gui_view()["contactPreview"] else None, seconds=150)
        self.gui_click("Accept contact")
        self.publish("invitation_accepted")
        self.receive("approved")
        self.wait("contact_approved", lambda: True if self.gui_view()["peerVisible"] else None,
                  seconds=120)
        self.dismiss_onboarding()
        self.peer.request("open_peer", label="Independent peer")
        self.wait("conversation", lambda: True if self.gui_view()["conversationOpen"]
                  and self.gui_view()["callEnabled"] else None)
        self.checks["signed_pair_and_explicit_approval"] = True

    def dismiss_onboarding(self):
        try:
            self.wait("onboarding_auto_dismissed", lambda: True if self.gui_view()["dialogTitle"] is None else None,
                      seconds=4)
        except TimeoutError as error:
            if str(error) != "call_onboarding_auto_dismissed": raise
            title = self.gui_view()["dialogTitle"]
            if title != "Connect with WebRTC": raise ValueError("call_onboarding_dialog_changed")
            self.peer.request("close_onboarding")
        self.wait("onboarding_dismissed", lambda: True if self.gui_view()["dialogTitle"] is None else None,
                  seconds=10)

    def connection(self):
        identity = self.request("profile.query", {"profile": self.profile})
        handles = identity.get("connections")
        if type(handles) is not list or len(handles) > 2: raise ValueError("call_connection_handles")
        ready = []
        for handle in handles:
            value = self.request("connection.snapshot", {"profile": self.profile, "connection": handle})
            observation = value.get("observation")
            if type(observation) is not dict: raise ValueError("call_connection_observation")
            if observation.get("messaging_ready") is True: ready.append(observation)
        if len(ready) != 1: return None
        return ready[0]

    def ready(self):
        if self.role == "peer":
            first = self.wait("connection_ready", self.connection)
            self.observations.append(first)
        else:
            self.wait("gui_ready", lambda: True if self.gui_view()["conversationOpen"] else None)
        self.publish("ready")
        self.receive("ready")
        self.checks["approved_route_ready"] = True

    def peer_inbound(self, text):
        def matched():
            messages = self.snapshot().get("messages")
            if type(messages) is not list: raise ValueError("call_messages_invalid")
            rows = [row for row in messages if row.get("kind") == "chat"
                    and row.get("direction") == "inbound" and row.get("text") == text]
            if len(rows) > 1: raise ValueError("call_message_duplicate")
            if rows and rows[0].get("contact_id") != self.contact["id"]:
                raise ValueError("call_message_wrong_contact")
            return rows[0] if rows else None
        return self.wait("peer_inbound", matched)

    def gui_inbound(self, text):
        def matched():
            view = self.gui_view(text)
            if view["matchedCount"] > 1: raise ValueError("call_gui_message_duplicate")
            return view if view["matchedInbound"] else None
        return self.wait("gui_inbound", matched)

    def gui_send(self, stage):
        text = text_for(self.pair_id, "gui", stage)
        self.peer.request("fill", label="Message Independent peer", value=text, scope="page")
        self.gui_click("Send message", "page")
        def delivered():
            view = self.gui_view(text)
            return view if view["matchedOutboundDelivered"] and view["matchedCount"] == 1 else None
        self.wait("gui_delivered", delivered)
        self.checks["gui_" + stage + "_sha256"] = digest(text)

    def peer_send(self, stage):
        text = text_for(self.pair_id, "peer", stage)
        result = self.request("message.enqueue", {"profile": self.profile,
            "recipient": self.contact["core_handle"], "kind": "text", "text": text}, str(uuid4()))
        if result.get("accepted") is not True or type(result.get("message")) is not str:
            raise ValueError("call_peer_enqueue")
        def delivered():
            value = self.request("message.query", {"profile": self.profile, "message": result["message"]})
            if (value.get("message") != result["message"] or value.get("text") != text
                    or value.get("recipient") != self.contact["core_handle"]):
                raise ValueError("call_peer_message_mismatch")
            return value if value.get("state") == "delivered" else None
        self.wait("peer_delivered", delivered)
        self.checks["peer_" + stage + "_sha256"] = digest(text)

    def before(self):
        if self.role == "gui":
            self.gui_send("before")
            self.publish("precall_gui_sent")
            self.receive("precall_peer_sent")
            self.gui_inbound(text_for(self.pair_id, "peer", "before"))
        else:
            self.receive("precall_gui_sent")
            self.peer_inbound(text_for(self.pair_id, "gui", "before"))
            self.peer_send("before")
            self.publish("precall_peer_sent")
            self.observations.append(self.wait("precall_ready", self.connection))
        self.checks["two_way_before"] = True

    def call(self, browser=None):
        if self.role == "gui":
            self.peer.request("call_peer", label="Call Independent peer")
            self.gui_click("Audio call")
            self.publish("call_started")
            self.wait("gui_in_call", lambda: True if self.gui_view()["status"].startswith("In call ·") else None,
                      seconds=150)
            self.publish("call_active")
            self.receive("call_active")
            self.receive("during_peer_sent")
            if not self.gui_view()["status"].startswith("In call ·"):
                raise ValueError("call_gui_not_active_during_message")
            self.gui_click("Hang up")
            self.wait("gui_call_ended", lambda: True if self.gui_view()["status"] == "" and
                self.gui_view()["dialogTitle"] == "Call Independent peer" else None)
            self.peer.request("close_call")
            self.gui_inbound(text_for(self.pair_id, "peer", "during"))
            self.publish("call_hungup")
            self.checks["gui_start_hangup_and_during_receipt_rendered_after"] = True
        else:
            self.receive("call_started")
            def incoming():
                calls = self.snapshot().get("calls")
                if type(calls) is not list or len(calls) > 1: raise ValueError("call_catalog_invalid")
                return (calls[0] if calls and calls[0].get("direction") == "inbound"
                    and calls[0].get("state") == "ringing" else None)
            call = self.wait("incoming_call", incoming)
            handle, call_id = call.get("core_handle"), call.get("id")
            if type(handle) is not str or type(call_id) is not str: raise ValueError("call_handle_invalid")
            media = self.request("call.media_query", {"profile": self.profile, "call": handle}).get("media")
            ice = self.request("call.ice_servers", {"profile": self.profile}).get("ice")
            if type(media) is not dict or type(media.get("remote_sdp")) is not str or type(ice) is not dict:
                raise ValueError("call_media_invalid")
            answer = browser.request("answer", offer=media["remote_sdp"], ice=ice)
            self.request("call.control", {"profile": self.profile, "action": "answer", "call_id": call_id,
                "sdp": answer["sdp"], "dtls_fingerprint": answer["fingerprint"]}, str(uuid4()))
            def media_ready():
                observation = browser.request("observe")
                return observation if (observation.get("connected") is True
                    and observation.get("selectedPair") is True and observation.get("captured") is True
                    and observation.get("remoteAudio") is True
                    and observation.get("outboundPackets", 0) > 0
                    and observation.get("inboundPackets", 0) > 0) else None
            media_observation = self.wait("real_media", media_ready, seconds=150, interval=2)
            self.checks["real_media_packets"] = {key: media_observation[key] for key in
                ("connected", "selectedPair", "captured", "remoteAudio", "outboundPackets", "inboundPackets")}
            self.publish("call_active")
            self.receive("call_active")
            self.observations.append(self.wait("during_ready", self.connection))
            self.peer_send("during")
            self.publish("during_peer_sent")
            self.receive("call_hungup")
            def ended():
                media = self.request("call.media_query", {"profile": self.profile, "call": handle}).get("media")
                if type(media) is not dict or media.get("id") != call_id:
                    raise ValueError("call_terminal_media_identity")
                return True if media.get("state") == "ended" else None
            self.wait("remote_hangup", ended)
            self.checks["browser_media_retired"] = browser.close()
            if not self.checks["browser_media_retired"]: raise ValueError("call_browser_cleanup")

    def after(self):
        if self.role == "gui":
            self.gui_send("after")
            self.publish("postcall_gui_sent")
            self.receive("postcall_peer_sent")
            self.gui_inbound(text_for(self.pair_id, "peer", "after"))
        else:
            self.receive("postcall_gui_sent")
            self.peer_inbound(text_for(self.pair_id, "gui", "after"))
            self.peer_send("after")
            self.publish("postcall_peer_sent")
            self.observations.append(self.wait("postcall_ready", self.connection))
            epochs = [row.get("runtime_epoch") for row in self.observations]
            sequences = [row.get("sequence") for row in self.observations]
            if (len(epochs) != 4 or len(set(epochs)) != 1 or any(type(item) is not int for item in sequences)
                    or sequences != sorted(sequences)
                    or not all(row.get("messaging_ready") is True and row.get("carrier") == "open"
                               for row in self.observations)):
                raise ValueError("call_public_runtime_continuity")
            self.checks["public_same_runtime_epoch"] = True
            self.checks["exact_physical_carrier_identity"] = "not_exposed_by_public_core_view"
        self.publish("done")
        self.receive("done")
        self.checks["two_way_after"] = True

    def run(self, browser=None):
        if self.role == "peer": self.peer_profile(); self.peer_pair()
        else: self.gui_pair()
        self.ready()
        self.before()
        self.call(browser)
        self.after()
        return self.checks
