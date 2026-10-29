import { MessageContent } from "../../src/MessageContent";
import { ArrowLeft, Check, LockKeyhole, Send, Phone, Video } from "lucide-react";
import "./link-preview-demo.css";

// Presentation fixture uses production components; no service or real chat data.
export function LinkPreviewDemo() {
  return <main className="preview-demo">
    <aside className="preview-demo__sidebar"><h1>Mesh Chat</h1><span>LINK PREVIEW DEMO</span><div className="preview-demo__contact"><span className="avatar avatar--small">JD</span><div><strong>Jamie</strong><p>Sent you a video</p></div></div><small><LockKeyhole size={14} /> Your conversations stay yours.</small></aside>
    <section className="preview-demo__conversation">
      <header className="conversation__header"><ArrowLeft size={19} /><span className="avatar avatar--small">JD</span><div><h2>Jamie</h2><span>Connected · WebRTC</span></div><div className="preview-demo__calls"><Phone size={19} /><Video size={21} /></div></header>
      <div className="preview-demo__messages"><div className="day-divider"><span>Today · Preview demo</span></div>
        <article className="message message--inbound"><MessageContent text={"This is the short film I was telling you about!\nhttps://youtu.be/aqz-KE-bpKQ"} /><footer><time>12:24 PM</time></footer></article>
        <article className="message message--outbound"><MessageContent text={"And a little internet history 🙂\nhttps://x.com/jack/status/20"} /><footer><time>12:25 PM</time><span className="delivery"><Check size={13} /> Delivered</span></footer></article>
        <article className="message message--inbound"><MessageContent text="More about the film: https://www.bigbuckbunny.org/" /><footer><time>12:26 PM</time></footer></article>
      </div>
      <div className="composer"><textarea aria-label="Message Jamie" placeholder="Message Jamie" rows={1} /><button type="button" aria-label="Send message"><Send size={20} /></button></div>
    </section>
  </main>;
}
