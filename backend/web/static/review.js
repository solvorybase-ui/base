"use strict";

(() => {
  const form = document.getElementById("review-decision-form");
  const progress = document.getElementById("open-count");
  if (!form || !progress) {
    return;
  }

  let prefetched = Array.from(
    document.querySelectorAll("template.review-prefetch-item")
  );
  let submitting = false;

  const currentItemId = () =>
    document.querySelector("article.product-card")?.dataset.reviewItemId || "";

  const setButtonsDisabled = (disabled) => {
    form.querySelectorAll("button[type='submit']").forEach((button) => {
      button.disabled = disabled;
    });
  };

  const preloadMainImages = (templates) => {
    templates.slice(0, 2).forEach((template) => {
      const source = template.dataset.mainImage;
      if (source) {
        const image = new Image();
        image.referrerPolicy = "no-referrer";
        image.src = source;
      }
    });
  };

  const refreshPrefetch = async (expectedItemId) => {
    try {
      const response = await fetch("/review", {
        credentials: "same-origin",
        headers: { "Accept": "text/html" }
      });
      if (!response.ok) {
        return;
      }
      const parsed = new DOMParser().parseFromString(
        await response.text(),
        "text/html"
      );
      const serverCurrent = parsed.querySelector("article.product-card");
      if (
        !serverCurrent ||
        serverCurrent.dataset.reviewItemId !== expectedItemId ||
        currentItemId() !== expectedItemId
      ) {
        return;
      }
      prefetched = Array.from(
        parsed.querySelectorAll("template.review-prefetch-item")
      ).map((template) => document.importNode(template, true));
      preloadMainImages(prefetched);

      const serverProgress = parsed.getElementById("open-count");
      if (serverProgress) {
        progress.dataset.openCount = serverProgress.dataset.openCount;
        progress.textContent = serverProgress.textContent.trim();
      }
    } catch (_error) {
      // The current product remains usable; the next action can fall back.
    }
  };

  const showPrefetchedProduct = () => {
    const next = prefetched.shift();
    const nextCard = next?.content.querySelector("article.product-card");
    const currentCard = document.querySelector("article.product-card");
    if (!next || !nextCard || !currentCard) {
      return false;
    }

    currentCard.replaceWith(nextCard.cloneNode(true));
    form.elements.review_session_item_id.value = next.dataset.itemId;
    document.title = next.dataset.title;

    const openCount = Number.parseInt(progress.dataset.openCount, 10);
    if (Number.isFinite(openCount)) {
      const nextCount = Math.max(0, openCount - 1);
      progress.dataset.openCount = String(nextCount);
      progress.textContent = `${nextCount} offen`;
    }
    return true;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitting || !event.submitter?.value) {
      return;
    }

    submitting = true;
    setButtonsDisabled(true);
    const body = new URLSearchParams();
    body.set(
      "review_session_item_id",
      form.elements.review_session_item_id.value
    );
    body.set("decision", event.submitter.value);

    try {
      const response = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
        },
        body: body.toString()
      });

      if (response.status === 409) {
        window.location.reload();
        return;
      }
      if (!response.ok) {
        window.location.reload();
        return;
      }
      if (!showPrefetchedProduct()) {
        window.location.assign("/review");
        return;
      }

      submitting = false;
      setButtonsDisabled(false);
      void refreshPrefetch(currentItemId());
    } catch (_error) {
      window.location.reload();
    }
  });
})();
