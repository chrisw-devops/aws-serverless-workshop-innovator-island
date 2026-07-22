(function () {
  const config = window.ISLAND_CONFIG || {};
  const apiBaseUrl = config.apiBaseUrl || "";

  const state = {
    attractions: [],
    stats: null,
  };

  const elements = {
    connectionStatus: document.querySelector("#connectionStatus"),
    stats: document.querySelector("#stats"),
    attractions: document.querySelector("#attractions"),
    refreshButton: document.querySelector("#refreshButton"),
    bookingForm: document.querySelector("#bookingForm"),
    attractionSelect: document.querySelector("select[name='attractionId']"),
    bookings: document.querySelector("#bookings"),
    photoForm: document.querySelector("#photoForm"),
    uploadState: document.querySelector("#uploadState"),
    events: document.querySelector("#events"),
  };

  elements.refreshButton.addEventListener("click", loadDashboard);
  elements.bookingForm.addEventListener("submit", createBooking);
  elements.photoForm.addEventListener("submit", uploadPhoto);

  loadDashboard();
  window.setInterval(loadDashboard, 30000);

  async function loadDashboard() {
    if (!apiBaseUrl) {
      setConnection("Missing config.js", "bad");
      return;
    }

    try {
      const [attractions, stats, bookings, events] = await Promise.all([
        request("/attractions"),
        request("/stats"),
        request("/bookings"),
        request("/events"),
      ]);

      state.attractions = attractions.attractions || [];
      state.stats = stats;
      renderStats(stats);
      renderAttractions(state.attractions);
      renderAttractionOptions(state.attractions);
      renderBookings(bookings.bookings || []);
      renderEvents(events.events || []);
      setConnection("Live", "good");
    } catch (error) {
      console.error(error);
      setConnection("API unavailable", "bad");
    }
  }

  async function createBooking(event) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload = Object.fromEntries(formData.entries());
    payload.partySize = Number(payload.partySize);

    try {
      await request("/bookings", { method: "POST", body: payload });
      event.currentTarget.reset();
      document.querySelector("input[name='partySize']").value = 2;
      await loadDashboard();
    } catch (error) {
      setConnection(error.message, "bad");
    }
  }

  async function uploadPhoto(event) {
    event.preventDefault();
    const file = new FormData(event.currentTarget).get("photo");
    if (!file || !file.name) return;

    elements.uploadState.textContent = "Requesting upload slot...";
    try {
      const presign = await request("/photos/presign", {
        method: "POST",
        body: { fileName: file.name, contentType: file.type },
      });
      const upload = await fetch(presign.uploadUrl, {
        method: "PUT",
        headers: { "content-type": file.type },
        body: file,
      });
      if (!upload.ok) throw new Error("S3 upload failed");
      elements.uploadState.textContent = `Uploaded to ${presign.key}`;
      event.currentTarget.reset();
    } catch (error) {
      elements.uploadState.textContent = error.message;
    }
  }

  async function changeStatus(id, status) {
    await request(`/attractions/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: { status },
    });
    await loadDashboard();
  }

  async function request(path, options = {}) {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      method: options.method || "GET",
      headers: { "content-type": "application/json" },
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      throw new Error(data && data.message ? data.message : `Request failed: ${response.status}`);
    }
    return data;
  }

  function renderStats(stats) {
    elements.stats.innerHTML = "";
    [
      ["Open", `${stats.openAttractions}/${stats.totalAttractions}`],
      ["Avg wait", `${stats.averageWait} min`],
      ["Bookings", stats.bookingsToday],
    ].forEach(([label, value]) => {
      const item = document.createElement("div");
      item.className = "stat";
      item.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
      elements.stats.appendChild(item);
    });
  }

  function renderAttractions(attractions) {
    elements.attractions.innerHTML = "";
    attractions.forEach((attraction) => {
      const card = document.createElement("article");
      card.className = "attraction-card";
      card.innerHTML = `
        <div class="card-topline">
          <span class="type">${attraction.type}</span>
          <span class="status ${attraction.status}">${attraction.status}</span>
        </div>
        <h3>${escapeHtml(attraction.name)}</h3>
        <p>${escapeHtml(attraction.area)}</p>
        <div class="wait-row">
          <strong>${attraction.waitMinutes}</strong>
          <span>minute wait</span>
        </div>
        <div class="capacity">Capacity ${attraction.capacityPerHour}/hr</div>
        <div class="actions">
          <button data-status="operating">Open</button>
          <button data-status="delayed">Delay</button>
          <button data-status="maintenance">Maint</button>
        </div>
      `;
      card.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => changeStatus(attraction.id, button.dataset.status));
      });
      elements.attractions.appendChild(card);
    });
  }

  function renderAttractionOptions(attractions) {
    const selected = elements.attractionSelect.value;
    elements.attractionSelect.innerHTML = attractions
      .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`)
      .join("");
    if (selected) elements.attractionSelect.value = selected;
  }

  function renderBookings(bookings) {
    elements.bookings.innerHTML = bookings.length
      ? bookings.map((booking) => `
        <div class="booking">
          <strong>${escapeHtml(booking.partyName)}</strong>
          <span>${booking.partySize} guests · ${escapeHtml(booking.attractionName)}</span>
          <small>${escapeHtml(booking.returnWindow)}</small>
        </div>
      `).join("")
      : "<p class='empty'>No reservations yet.</p>";
  }

  function renderEvents(events) {
    elements.events.innerHTML = events.map((event) => `
      <div class="event ${event.severity}">
        <time>${escapeHtml(event.time)}</time>
        <div>
          <strong>${escapeHtml(event.title)}</strong>
          <span>${escapeHtml(event.area)}</span>
        </div>
      </div>
    `).join("");
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[character]));
  }

  function setConnection(text, mode) {
    elements.connectionStatus.textContent = text;
    elements.connectionStatus.dataset.mode = mode;
  }
})();
