const BACKEND_URL = "http://localhost:8080"; // change to 8000 if your backend runs there

function insertFactLensStyles() {
  if (document.getElementById("factlens-style")) return;

  const style = document.createElement("style");
  style.id = "factlens-style";
  style.textContent = `
    .factlens-card {
      margin-top: 8px;
      padding: 10px 16px;
      border-radius: 9999px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 12px;
      line-height: 1.4;
      font-family: var(--font-family, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
      background-color: var(--newRedditTheme-field, #272729);
      border: 1px solid var(--newRedditTheme-line, #343536);
      color: var(--newRedditTheme-bodyText, #D7DADC);
      box-sizing: border-box;
    }

    .factlens-main {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      flex: 1 1 auto;
      overflow: hidden;
    }

    .factlens-label {
      font-weight: 600;
      color: var(--newRedditTheme-metaText, #818384);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .factlens-dot {
      color: var(--newRedditTheme-metaText, #818384);
    }

    .factlens-verdict-pill {
      padding: 2px 8px;
      border-radius: 9999px;
      font-weight: 600;
      font-size: 11px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .factlens-verdict-true {
      background-color: rgba(34, 197, 94, 0.15);
      color: #22c55e;
    }

    .factlens-verdict-false {
      background-color: rgba(248, 113, 113, 0.18);
      color: #f87171;
    }

    .factlens-verdict-partly {
      background-color: rgba(251, 191, 36, 0.22);
      color: #fbbf24;
    }

    .factlens-verdict-unverifiable {
      background-color: rgba(148, 163, 184, 0.2);
      color: #9ca3af;
    }

    .factlens-reason {
      color: var(--newRedditTheme-metaText, #818384);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 420px;
    }

    .factlens-link {
      flex-shrink: 0;
      font-weight: 500;
      color: var(--newRedditTheme-linkText, #4fbcff);
      text-decoration: none;
      cursor: pointer;
    }

    .factlens-link:hover {
      text-decoration: underline;
    }
  `;
  document.head.appendChild(style);
}

(async function () {
  // Wait for Reddit to render
  await new Promise((r) => setTimeout(r, 1500));

  insertFactLensStyles();

  // Try to find the post title and body
  let titleEl = document.querySelector("h1");
  let bodyEl = document.querySelector('[data-test-id="post-content"]');

  // Fallback for some layouts
  if (!titleEl) {
    titleEl = document.querySelector("h2");
  }

  if (!titleEl) {
    console.log("FactLens: no title element found on this page.");
    return;
  }

 const title = titleEl.innerText || "";
const body = bodyEl ? bodyEl.innerText : "";

// Prefer body text for verification; fall back to title only if body is empty
const postText = (body || title).trim();

  if (!postText) {
    console.log("FactLens: no post text to verify.");
    return;
  }

  console.log("FactLens: verifying post:", postText);

  // Call backend
  let data;
  try {
    const res = await fetch(`${BACKEND_URL}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: postText }),
    });

    if (!res.ok) {
      console.error("FactLens: backend error", res.status);
      data = {
        verdict: "Unverifiable",
        confidence: 0.5,
        reasoning: "Unable to reach verification service.",
      };
    } else {
      data = await res.json();
    }
  } catch (err) {
    console.error("FactLens: error calling backend", err);
    data = {
      verdict: "Unverifiable",
      confidence: 0.5,
      reasoning: "Unable to reach verification service.",
    };
  }

  console.log("FactLens: verdict", data);

  // Build card
  const card = document.createElement("div");
  card.className = "factlens-card";

  const main = document.createElement("div");
  main.className = "factlens-main";

  const label = document.createElement("span");
  label.className = "factlens-label";
  label.textContent = "FactLens";

  const dot = document.createElement("span");
  dot.className = "factlens-dot";
  dot.textContent = "•";

  const verdictPill = document.createElement("span");
  verdictPill.className = "factlens-verdict-pill";

  const verdict = (data.verdict || "Unverifiable").toLowerCase();
  if (verdict === "true") {
    verdictPill.classList.add("factlens-verdict-true");
  } else if (verdict === "false") {
    verdictPill.classList.add("factlens-verdict-false");
  } else if (verdict === "partly true") {
    verdictPill.classList.add("factlens-verdict-partly");
  } else {
    verdictPill.classList.add("factlens-verdict-unverifiable");
  }

  const verdictText = document.createElement("span");
  const conf = typeof data.confidence === "number" ? data.confidence : 0.5;
  verdictText.textContent = `${data.verdict || "Unverifiable"} (${(
    conf * 100
  ).toFixed(0)}%)`;

  verdictPill.appendChild(verdictText);

  const reasonSpan = document.createElement("span");
  reasonSpan.className = "factlens-reason";
  const reason = data.reasoning || "";
  const shortReason =
    reason.length > 140 ? reason.slice(0, 140).trimEnd() + "…" : reason;
  reasonSpan.textContent = shortReason
    ? `— ${shortReason}`
    : "— Click for full explanation.";

  main.appendChild(label);
  main.appendChild(dot);
  main.appendChild(verdictPill);
  main.appendChild(reasonSpan);

  const viewLink = document.createElement("a");
  viewLink.className = "factlens-link";
  viewLink.textContent = "View details";
  viewLink.href = "#";

  viewLink.addEventListener("click", (e) => {
    e.preventDefault();
    const dashboardUrl =
      chrome.runtime.getURL("dashboard.html") +
      "?text=" +
      encodeURIComponent(postText);
    window.open(dashboardUrl, "_blank");
  });

  card.appendChild(main);
  card.appendChild(viewLink);

  // Insert under title
  if (titleEl.parentElement) {
    titleEl.parentElement.appendChild(card);
  } else {
    document.body.prepend(card);
  }
})();