package com.meshchat.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PendingInvitationTest {
  private fun workspaceInvite(signature: String = "signed-owner-proof"): String = """
    {"v":1,"type":"workspace_invite","workspace_id":"11111111-1111-4111-8111-111111111111","genesis_digest":"${"a".repeat(64)}","offered_manifest_digest":"${"b".repeat(64)}","genesis":{"v":1,"type":"workspace_genesis","workspace_id":"11111111-1111-4111-8111-111111111111","name":"Lakewatcher Operations"},"offered_manifest":{"v":1,"type":"workspace_manifest_root","workspace_id":"11111111-1111-4111-8111-111111111111","epoch":1,"status":"active"},"authority_chain":[],"nonce":"aW52aXRhdGlvbi1ub25jZQ","created_at":1800000000,"expires_at":1800000900,"use_limit":1,"signature":"$signature"}
  """.trimIndent()

  private fun workspaceDeviceLink(signature: String = "signed-sponsor-proof"): String = """
    {"v":1,"type":"workspace_device_link_offer","workspace_id":"11111111-1111-4111-8111-111111111111","link_id":"22222222-2222-4222-8222-222222222222","base_manifest_epoch":1,"base_manifest_digest":"${"b".repeat(64)}","member_id":"33333333-3333-4333-8333-333333333333","sponsor_device_id":"44444444-4444-4444-8444-444444444444","sponsor_destination":"${"c".repeat(32)}","genesis":{"v":1,"type":"workspace_genesis","workspace_id":"11111111-1111-4111-8111-111111111111","name":"Lakewatcher Operations"},"offered_manifest":{"v":1,"type":"workspace_manifest_root","workspace_id":"11111111-1111-4111-8111-111111111111","epoch":1,"status":"active"},"authority_chain":[],"bootstrap_manifests":[],"nonce":"ZGV2aWNlLWxpbmstbm9uY2U","replay_key":"55555555-5555-4555-8555-555555555555","created_at":1800000000,"expires_at":1800000900,"use_limit":1,"signature":"$signature"}
  """.trimIndent()

  @Test
  fun acceptsSupportedLinksAndDocuments() {
    assertEquals("meshchat://invite/abc_DEF-123", PendingInvitation.validate("meshchat://invite/abc_DEF-123"))
    assertEquals("MESHCHAT2:abc_DEF-123", PendingInvitation.validate("MESHCHAT2:abc_DEF-123"))
    assertEquals("MESHCHAT3:abc_DEF-123", PendingInvitation.validate("MESHCHAT3:abc_DEF-123"))
    assertEquals("MESHCHAT4:abc_DEF-123", PendingInvitation.validate("MESHCHAT4:abc_DEF-123"))
    assertEquals("MESHWORKSPACE1:abc_DEF-123", PendingInvitation.validate("MESHWORKSPACE1:abc_DEF-123"))
    assertEquals("MESHWORKSPACE2:abc_DEF-123", PendingInvitation.validate("MESHWORKSPACE2:abc_DEF-123"))
    assertEquals("MESHWORKSPACE3:abc_DEF-123", PendingInvitation.validate("MESHWORKSPACE3:abc_DEF-123"))
    assertEquals("MESHWORKSPACE4:abc_DEF-123", PendingInvitation.validate("MESHWORKSPACE4:abc_DEF-123"))
    assertEquals("MESHCONNECT1:abc_DEF-123", PendingInvitation.validate("MESHCONNECT1:abc_DEF-123"))
    assertEquals("MESHROUTE1:abc_DEF-123", PendingInvitation.validate("MESHROUTE1:abc_DEF-123"))
    assertEquals("MESHWORKSPACEDEVICE1:abc_DEF-123", PendingInvitation.validate("MESHWORKSPACEDEVICE1:abc_DEF-123"))
    val document = "{\"v\":1,\"label\":\"Peer\",\"public_identity\":\"a\",\"destination\":\"b\",\"created_at\":1,\"expires_at\":2,\"hints\":[],\"signature\":\"c\"}"
    assertEquals(document, PendingInvitation.validate(document))
    val remote = "{\"v\":2,\"type\":\"remote_invitation\",\"purpose\":\"personal\",\"inner\":\"signed\",\"inner_digest\":\"digest\",\"profile\":{},\"created_at\":1,\"expires_at\":2,\"signer_destination\":\"destination\",\"signature\":\"signature\"}"
    assertEquals(remote, PendingInvitation.validate(remote))
    val workspaceRemote = remote.replace("\"personal\"", "\"workspace\"")
    assertEquals(workspaceRemote, PendingInvitation.validate(workspaceRemote))
    val participant = "{\"v\":3,\"type\":\"participant_invitation\",\"purpose\":\"personal\",\"inner\":\"signed\",\"inner_digest\":\"digest\",\"access\":{},\"created_at\":1,\"expires_at\":2,\"signer_destination\":\"destination\",\"signature\":\"signature\"}"
    assertEquals(participant, PendingInvitation.validate(participant))
    val email = "{\"v\":4,\"type\":\"email_invitation\",\"purpose\":\"workspace\",\"inner\":\"signed\",\"inner_digest\":\"digest\",\"inviter_access\":null,\"reply_challenge\":\"challenge\",\"created_at\":1,\"expires_at\":2,\"signer_destination\":\"destination\",\"signature\":\"signature\"}"
    assertEquals(email, PendingInvitation.validate(email))
  }

  @Test
  fun recognizesOnlyMeshChatDocumentSuffixes() {
    assertTrue(PendingInvitation.isSupportedFileName("Invite.MESHCHAT-INVITE"))
    assertTrue(PendingInvitation.isSupportedFileName("reply.meshchat-connect"))
    assertTrue(PendingInvitation.isSupportedFileName("route.meshchat-route"))
    assertTrue(PendingInvitation.isSupportedFileName("legacy.meshchat"))
    assertTrue(PendingInvitation.isSupportedFileName("invite.meshchat-invite.json"))
    assertTrue(PendingInvitation.isSupportedFileName("invite.json"))
    assertFalse(PendingInvitation.isSupportedFileName("invite.txt"))
  }

  @Test
  fun preservesTheLargestFamilyBoundForDocumentIngress() {
    val prefix = "MESHWORKSPACEDEVICE1:"
    val atLimit = prefix + "a".repeat(PendingInvitation.MAX_DOCUMENT_BYTES - prefix.length)
    assertNotNull(PendingInvitation.validate(atLimit))
    assertNull(PendingInvitation.validate("${atLimit}a"))
  }

  @Test
  fun acceptsRawWorkspaceDocumentsWithExactServiceEnvelopesAndBounds() {
    val invite = workspaceInvite()
    val deviceLink = workspaceDeviceLink()
    assertEquals(invite, PendingInvitation.validate(invite))
    assertEquals(deviceLink, PendingInvitation.validate(deviceLink))

    val emptyInviteSize = workspaceInvite("").toByteArray(Charsets.UTF_8).size
    val inviteAtLimit = workspaceInvite(
      "s".repeat(PendingInvitation.MAX_WORKSPACE_INVITE_DOCUMENT_BYTES - emptyInviteSize)
    )
    assertEquals(inviteAtLimit, PendingInvitation.validate(inviteAtLimit))
    assertNull(PendingInvitation.validate("${inviteAtLimit.dropLast(2)}s\"}"))

    val emptyLinkSize = workspaceDeviceLink("").toByteArray(Charsets.UTF_8).size
    val linkAtLimit = workspaceDeviceLink(
      "s".repeat(PendingInvitation.MAX_DEVICE_LINK_DOCUMENT_BYTES - emptyLinkSize)
    )
    assertEquals(linkAtLimit, PendingInvitation.validate(linkAtLimit))
    assertNull(PendingInvitation.validate("${linkAtLimit.dropLast(2)}s\"}"))
  }

  @Test
  fun rejectsRawWorkspaceDocumentsWithNonSchemaEnvelopes() {
    val invite = workspaceInvite()
    assertNull(PendingInvitation.validate(invite.replaceFirst("\"v\":1", "\"v\":2")))
    assertNull(
      PendingInvitation.validate(
        invite.replaceFirst("\"type\":\"workspace_invite\"", "\"type\":\"workspace_join\"")
      )
    )
    assertNull(PendingInvitation.validate("${invite.dropLast(1)},\"private_path\":\"secret\"}"))

    val deviceLink = workspaceDeviceLink()
    assertNull(PendingInvitation.validate(deviceLink.replaceFirst("\"v\":1", "\"v\":2")))
    assertNull(
      PendingInvitation.validate(
        deviceLink.replaceFirst(
          "\"type\":\"workspace_device_link_offer\"",
          "\"type\":\"workspace_device_link_acceptance\"",
        )
      )
    )
    assertNull(PendingInvitation.validate("${deviceLink.dropLast(1)},\"private_path\":\"secret\"}"))
  }

  @Test
  fun rejectsMalformedOversizedAndUnrelatedValues() {
    assertNull(PendingInvitation.validate("meshchat://notification/${"a".repeat(64)}"))
    assertNull(PendingInvitation.validate("meshchat://invite/abc?leak=1"))
    assertNull(PendingInvitation.validate("meshchat://invite/abc/extra"))
    assertNull(PendingInvitation.validate("https://example.invalid/invite"))
    assertNull(PendingInvitation.validate("MESHCHAT1:${"a".repeat(33 * 1024)}"))
    assertNull(PendingInvitation.validate("C:\\private\\invite.meshchat"))
    assertNull(PendingInvitation.validate("{\"v\":1,\"public_identity\":\"a\",\"destination\":\"b\",\"signature\":\"c\"}"))
    assertNull(PendingInvitation.validate("{\"v\":1,\"label\":\"Peer\",\"public_identity\":\"a\",\"destination\":\"b\",\"created_at\":1,\"expires_at\":2,\"hints\":[],\"signature\":\"c\",\"path\":\"private\"}"))
  }
}
