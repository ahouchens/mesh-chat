package com.meshchat.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PendingInvitationTest {
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
