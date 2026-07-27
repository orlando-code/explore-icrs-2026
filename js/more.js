import QRCode from "https://esm.sh/qrcode@1.5.4";
import { canonicalSiteUrl } from "./config.js";

export function createShareView(_siteData, elements) {
  function shareUrl() {
    if (
      location.hostname === "orlando-codes.com" ||
      location.hostname === "www.orlando-codes.com" ||
      location.hostname.endsWith("github.io")
    ) {
      return canonicalSiteUrl();
    }
    return location.href.split("#")[0];
  }

  function setStatus(message, isError = false) {
    if (!elements.status) return;
    elements.status.textContent = message || "";
    elements.status.classList.toggle("error", isError);
    elements.status.hidden = !message;
  }

  async function renderQr() {
    const url = shareUrl();
    if (elements.url) {
      elements.url.textContent = url;
      elements.url.title = "Click to copy link";
    }
    if (!elements.qrCanvas) return;

    const size = Math.min(280, Math.max(200, window.innerWidth - 56));
    elements.qrCanvas.width = size;
    elements.qrCanvas.height = size;

    await QRCode.toCanvas(elements.qrCanvas, url, {
      width: size,
      margin: 2,
      color: {
        dark: "#14212b",
        light: "#ffffff",
      },
    });
  }

  async function copyLink() {
    const url = shareUrl();
    try {
      await navigator.clipboard.writeText(url);
      setStatus("Link copied to clipboard.");
      return true;
    } catch {
      setStatus("Could not copy link.", true);
      return false;
    }
  }

  function bindEvents() {
    elements.url?.addEventListener("click", () => {
      copyLink();
    });
  }

  bindEvents();

  return {
    render: renderQr,
    copyLink,
    shareUrl,
  };
}
