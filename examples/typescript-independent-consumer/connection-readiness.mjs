export async function connectionMessagingReady(client, profile, connection) {
  const value = await client.connectionSnapshot(profile, connection);
  return value.observation.messaging_ready === true;
}
