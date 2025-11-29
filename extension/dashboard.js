const BACKEND_URL = "http://localhost:8080"; // same as in content_script.js

function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

async function loadAnalysis() {
  const loadingEl = document.getElementById("loading");
  const cardEl = document.getElementById("card");
  const claimEl = document.getElementById("claim");
  const verdictPillEl = document.getElementById("verdictPill");
  const confidenceEl = document.getElementById("confidence");
  const reasoningEl = document.getElementById("reasoning");
  const citationsEl = document.getElementById("citations");

  const text = getQueryParam("text");
  if (!text) {
    loadingEl.textContent = "No claim text provided.";
    return;
  }

  try {
    const res = await fetch(`${BACKEND_URL}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    if (!res.ok) {
      loadingEl.textContent = `Backend error: ${res.status}`;
      return;
    }

    const data = await res.json();
    console.log("FactLens dashboard: received", data);

    loadingEl.style.display = "none";
    cardEl.style.display = "block";

    // Claim
    claimEl.textContent = data.claim || text;

    // Verdict
    const verdict = (data.verdict || "Unverifiable").toLowerCase();
    verdictPillEl.textContent = data.verdict || "Unverifiable";

    verdictPillEl.classList.remove(
      "factlens-verdict-true",
      "factlens-verdict-false",
      "factlens-verdict-partly",
      "factlens-verdict-unverifiable"
    );
    if (verdict === "true") {
      verdictPillEl.classList.add("factlens-verdict-true");
    } else if (verdict === "false") {
      verdictPillEl.classList.add("factlens-verdict-false");
    } else if (verdict === "partly true") {
      verdictPillEl.classList.add("factlens-verdict-partly");
    } else {
      verdictPillEl.classList.add("factlens-verdict-unverifiable");
    }

    const conf = typeof data.confidence === "number" ? data.confidence : 0.5;
    confidenceEl.textContent = `Confidence: ${(conf * 100).toFixed(1)}%`;

    // Reasoning
    reasoningEl.textContent =
      data.reasoning || "No reasoning available for this claim.";

    // Citations
    citationsEl.innerHTML = "";
    if (!data.citations || data.citations.length === 0) {
      const noCit = document.createElement("div");
      noCit.className = "factlens-citation";
      noCit.textContent = "No citations available for this claim.";
      citationsEl.appendChild(noCit);
    } else {
      for (const cit of data.citations) {
        const citDiv = document.createElement("div");
        citDiv.className = "factlens-citation";

        const titleSpan = document.createElement("span");
        titleSpan.className = "factlens-citation-title";
        titleSpan.textContent = `Fact: ${cit.fact_id}`;

        const metaSpan = document.createElement("span");
        metaSpan.className = "factlens-citation-meta";
        metaSpan.textContent = ` – Source: ${cit.source_id}`;

        citDiv.appendChild(titleSpan);
        citDiv.appendChild(metaSpan);

        citationsEl.appendChild(citDiv);
      }
    }
  } catch (err) {
    console.error("FactLens dashboard: error", err);
    loadingEl.textContent = "Error loading analysis.";
  }
}

document.addEventListener("DOMContentLoaded", loadAnalysis);