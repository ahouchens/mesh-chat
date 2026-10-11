package com.meshchat.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PendingInvitationTest {
  @Test
  fun acceptsSupportedLinksAndDocuments() {
    assertEquals("meshchat://invite/abc_DEF-123", PendingInvitation.validate("meshchat://invite/abc_DEF-123"))
    assertEquals("MESHWORKSPACE1:abc_DEF-123", PendingInvitation.validate("MESHWORKSPACE1:abc_DEF-123"))
    assertEquals("MESHWORKSPACEDEVICE1:abc_DEF-123", PendingInvitation.validate("MESHWORKSPACEDEVICE1:abc_DEF-123"))
    val document = "{\"v\":1,\"label\":\"Peer\",\"public_identity\":\"a\",\"destination\":\"b\",\"created_at\":1,\"expires_at\":2,\"hints\":[],\"signature\":\"c\"}"
    assertEquals(document, PendingInvitation.validate(document))
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
