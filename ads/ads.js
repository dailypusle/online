/* DailyPulse category-aware sponsored campaign renderer.
   Include this file from index.html with:
   <script src="ads/ads.js" defer></script>
*/
(() => {
  const news = document.getElementById("news");
  if (!news) return;

  const configUrl = new URL("ads/ads.json", document.baseURI);
  let campaignsByCategory = null;
  let loadPromise = null;
  let renderQueued = false;

  function safeHttpUrl(value, base = document.baseURI) {
    try {
      const url = new URL(value, base);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  }

  function loadCampaigns() {
    if (!loadPromise) {
      loadPromise = fetch(configUrl.href + "?t=" + Date.now(), { cache: "no-store" })
        .then(response => {
          if (!response.ok) throw new Error("Ad configuration returned HTTP " + response.status);
          return response.json();
        })
        .then(data => {
          if (!data || !data.categories || typeof data.categories !== "object") {
            throw new Error("Ad configuration has no categories object");
          }
          campaignsByCategory = data.categories;
          return campaignsByCategory;
        })
        .catch(error => {
          loadPromise = null;
          throw error;
        });
    }
    return loadPromise;
  }

  function makeAd(campaign) {
    if (!campaign || campaign.enabled !== true) return null;
    const destination = safeHttpUrl(campaign.destinationUrl);
    const imageUrl = safeHttpUrl(campaign.image);
    const advertiser = String(campaign.advertiser || "Sponsored").trim();
    const headline = String(campaign.headline || "").trim();
    const body = String(campaign.body || "").trim();
    if (!destination || !imageUrl || !headline) return null;

    const article = document.createElement("article");
    article.className = "story sponsored-story";
    article.dataset.sponsored = "true";

    const imageLink = document.createElement("a");
    imageLink.href = destination;
    imageLink.target = "_blank";
    imageLink.rel = "noopener sponsored";
    imageLink.setAttribute("aria-label", "Sponsored by " + advertiser);

    const image = document.createElement("img");
    image.className = "photo";
    image.src = imageUrl;
    image.alt = advertiser + " advertisement";
    image.loading = "lazy";
    imageLink.appendChild(image);

    const text = document.createElement("div");
    text.className = "text";

    const label = document.createElement("div");
    label.className = "meta sponsored-label";
    label.textContent = "Sponsored · " + advertiser;

    const heading = document.createElement("h2");
    const link = document.createElement("a");
    link.href = destination;
    link.target = "_blank";
    link.rel = "noopener sponsored";
    link.textContent = headline;
    heading.appendChild(link);

    text.append(label, heading);
    if (body) {
      const description = document.createElement("p");
      description.className = "description";
      description.textContent = body;
      text.appendChild(description);
    }

    article.append(imageLink, text);
    return article;
  }

  async function renderAd() {
    try {
      const category = news.dataset.category || "top";
      const categories = await loadCampaigns();
      // A top campaign may also run in other categories; category-specific
      // campaigns are preferred and shown before any top-wide campaign.
      const candidates = [
        ...(Array.isArray(categories[category]) ? categories[category] : []),
        ...(category !== "top" && Array.isArray(categories.top) ? categories.top : [])
      ];
      const enabled = candidates.filter(campaign => campaign && campaign.enabled === true);
      const existing = news.querySelector(":scope > .sponsored-story");
      const campaign = enabled[0];

      if (!campaign) {
        existing?.remove();
        return;
      }
      if (existing && existing.dataset.campaignId === String(campaign.id || "")) return;

      const card = makeAd(campaign);
      if (!card) {
        existing?.remove();
        return;
      }
      card.dataset.campaignId = String(campaign.id || "");
      existing?.remove();
      news.prepend(card);
    } catch (error) {
      console.warn("DailyPulse sponsored ad unavailable:", error.message);
    }
  }

  function scheduleRender() {
    if (renderQueued) return;
    renderQueued = true;
    queueMicrotask(() => {
      renderQueued = false;
      renderAd();
    });
  }

  const observer = new MutationObserver(scheduleRender);
  observer.observe(news, { childList: true, attributes: true, attributeFilter: ["data-category"] });
  scheduleRender();
})();
