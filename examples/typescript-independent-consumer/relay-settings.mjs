// Fresh-profile qualification deliberately uses the consented TURN broker.
export function freshRelaySettings(settings) {
  if (settings.turn_configured !== false || settings.turn_username !== null) {
    throw new Error("unexpected_static_turn_configuration");
  }
  return {
    stun_urls: settings.stun_urls,
    turn_url: settings.turn_url,
    turn_username: settings.turn_username,
    turn_broker_url: settings.turn_broker_url,
    signal_mailbox_url: settings.signal_mailbox_url,
    store_call_signaling: settings.store_call_signaling,
    turn_broker_consent: true,
    relay_only: true,
  };
}
