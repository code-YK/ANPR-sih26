import { useState } from "react";

import { useToast } from "./Toast.jsx";
import Modal from "./Modal.jsx";

// A same-origin-in-prod, credentialed image URL can't just get a plain
// `<a download>` -- cross-origin (dev: localhost:5173 -> :8000), the
// browser navigates instead of saving. Fetching it as a blob first
// sidesteps that: the object URL handed to the anchor is always
// same-origin to this page. "include" (not "same-origin"), because in
// dev this fetch genuinely IS cross-origin (different port) -- the
// session cookie only rides along because the two hosts are same-site,
// the same reasoning recordingMediaUrl's own comment in api.js gives for
// why a plain <img>/<video src> already works without this.
//
// The cache-busting query param is load-bearing, not cosmetic: this
// exact URL was very likely already loaded moments earlier by a plain,
// non-CORS <img> in the table this lightbox opened from (confirmed via
// direct testing) -- Chrome holds that as an opaque cached response, and
// a later `cors`-mode fetch() to the *identical* URL fails outright
// rather than issuing a fresh request. A trailing `?_dl=<timestamp>`
// makes this a technically different URL, so it never touches that
// cached entry.
async function downloadViaBlob(url, filename, showToast) {
  try {
    const bustedUrl = url + (url.includes("?") ? "&" : "?") + "_dl=" + Date.now();
    const resp = await fetch(bustedUrl, { credentials: "include" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(blobUrl);
  } catch (err) {
    showToast("Download failed: " + err.message);
  }
}

// A larger, dedicated view of one still image, with a real download --
// separate from anything that opens a video player, so "see this crop
// clearly" and "watch the clip" are two different, non-competing clicks
// on the same thumbnail's row.
export default function ImageLightbox({ src, filename, open, onClose }) {
  const showToast = useToast();
  const [downloading, setDownloading] = useState(false);

  async function handleDownload() {
    setDownloading(true);
    try {
      await downloadViaBlob(src, filename, showToast);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} wide>
      {src && (
        <>
          <img src={src} alt="" style={{ width: "100%", borderRadius: 6, display: "block" }} />
          <div className="actions">
            <button type="button" className="secondary" onClick={onClose}>
              Close
            </button>
            <button type="button" className="primary" onClick={handleDownload} disabled={downloading}>
              {downloading ? "Downloading…" : "Download image"}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
