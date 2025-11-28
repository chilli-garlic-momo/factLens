(async function () {
  // 1. Wait for Reddit to render
  await new Promise((r) => setTimeout(r, 1500));

  // 2. Try to find the post title and body
  let titleEl = document.querySelector("h1");
  let bodyEl = document.querySelector('[data-test-id="post-content"]');

  // Fallback: some layouts may use h2
  if (!titleEl) {
    titleEl = document.querySelector("h2");
  }

  if (!titleEl) {
    console.log("FactLens: no title element found on this page.");
    return;
  }

  const title = titleEl.innerText || "";
  const body = bodyEl ? bodyEl.innerText : "";
  const postText = (title + "\n\n" + body).trim();

  if (!postText) {
    console.log("FactLens: no post text to verify.");
    return;
  }

  console.log("FactLens: verifying post:", postText);

  // 3. Call backend
  let data;
  try {
    const res = await fetch("http://localhost:8000/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: postText })
    });

    if (!res.ok) {
      console.error("FactLens: backend error", res.status);
      return;
    }

    data = await res.json();
    console.log("FactLens: verdict", data);
  } catch (err) {
    console.error("FactLens: error calling backend", err);
    return;
  }

  // 4. Create the overlay chip
  const chip = document.createElement("div");
  chip.style.marginTop = "8px";
  chip.style.padding = "8px 12px";
  chip.style.borderRadius = "999px";
  chip.style.fontSize = "12px";
  chip.style.fontFamily =
    "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  chip.style.display = "inline-flex";
  chip.style.alignItems = "center";
  chip.style.gap = "8px";
  chip.style.border = "1px solid #ccc";
  chip.style.backgroundColor = "#f7f7f7";

  let color = "#999";
  if (data.verdict === "True") color = "#16a34a"; // green
  else if (data.verdict === "False") color = "#dc2626"; // red
  else if (data.verdict === "Partly True") color = "#d97706"; // amber

  const badge = document.createElement("span");
  badge.textContent = `FactLens: ${data.verdict} (${(data.confidence * 100).toFixed(
    0
  )}%)`;
  badge.style.fontWeight = "600";
  badge.style.color = color;

  const briefReason = document.createElement("span");
  const shortReason =
    (data.reasoning || "").length > 100
      ? data.reasoning.slice(0, 100) + "…"
      : data.reasoning || "";
  briefReason.textContent = shortReason ? `– ${shortReason}` : "";
  briefReason.style.color = "#555";

  const viewLink = document.createElement("a");
  viewLink.textContent = "View details";
  viewLink.href = "#";
  viewLink.style.marginLeft = "8px";
  viewLink.style.color = "#2563eb";
  viewLink.style.textDecoration = "underline";
  viewLink.style.cursor = "pointer";

  viewLink.addEventListener("click", (e) => {
    e.preventDefault();
    const dashboardUrl =
      chrome.runtime.getURL("dashboard.html") +
      "?text=" +
      encodeURIComponent(postText);
    window.open(dashboardUrl, "_blank");
  });

  chip.appendChild(badge);
  chip.appendChild(briefReason);
  chip.appendChild(viewLink);

  // 5. Insert chip below title
  if (titleEl.parentElement) {
    titleEl.parentElement.appendChild(chip);
  } else {
    document.body.prepend(chip);
  }
})();