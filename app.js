const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const modalRoot = $("#modal-root");
const toastRegion = $("#toast-region");
let currentUser = null;
let centers = [];

const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const money = (value) => new Intl.NumberFormat("en-IN", {
  style: "currency", currency: "INR", maximumFractionDigits: 0
}).format(Number(value) || 0);
const dateLabel = (value) => value ? new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
  day: "numeric", month: "short", year: "numeric"
}) : "—";
const statusPill = (status) => `<span class="status-pill ${escapeHTML(status)}">${escapeHTML(status)}</span>`;

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) throw new Error(data.error || "Something went wrong. Please try again.");
  return data;
}

function toast(message, error = false) {
  const item = document.createElement("div");
  item.className = `toast${error ? " error" : ""}`;
  item.textContent = message;
  toastRegion.append(item);
  setTimeout(() => item.remove(), 4000);
}

function showModal(title, subtitle, content, { wide = false, eyebrow = "NESTCARE" } = {}) {
  modalRoot.innerHTML = `<div class="modal-backdrop" data-close-modal><section class="modal${wide ? " modal-wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><button class="modal-close" type="button" aria-label="Close dialog" data-close-modal>×</button><div class="modal-eyebrow">${escapeHTML(eyebrow)}</div><h2 id="modal-title">${escapeHTML(title)}</h2>${subtitle ? `<p class="modal-subtitle">${escapeHTML(subtitle)}</p>` : ""}${content}</section></div>`;
  const firstInput = $("input, select, button", $(".modal", modalRoot));
  if (firstInput) firstInput.focus();
}

function closeModal() { modalRoot.innerHTML = ""; }

function accountChanged() {
  const area = $("#account-area");
  if (!currentUser) {
    area.innerHTML = `<button class="button button-outline button-small" id="sign-in-button">Log in</button><button class="button button-dark button-small" id="join-button">Get started <span>↗</span></button>`;
    return;
  }
  const badge = currentUser.status === "pending" ? " · application pending" : "";
  area.innerHTML = `<span class="account-name">${escapeHTML(currentUser.name.split(" ")[0])}${badge}</span><button class="button button-outline button-small" id="notifications-button" aria-label="Notifications">♡</button><button class="button button-dark button-small" id="dashboard-button">My space <span>↗</span></button><button class="button button-outline button-small" id="logout-button">Log out</button>`;
}

async function loadUser() {
  const data = await api("/api/me");
  currentUser = data.user;
  accountChanged();
  if (currentUser) {
    $("#dashboard").classList.remove("hidden");
    await loadDashboard();
  }
}

function centerCard(center, index) {
  const plan = center.plans?.daily ?? center.plans?.hourly ?? 0;
  const cadence = center.plans?.daily != null ? "/ day" : "/ hour";
  const ages = center.age_groups.slice(0, 3).map((age) => `<span class="tag">${escapeHTML(age)}</span>`).join("");
  return `<article class="center-card">
    <div class="center-cover cover-${index % 3 + 1}"><span class="cover-sun"></span><span class="cover-tree"></span><span class="cover-house"></span><span class="cover-label">Verified with care</span></div>
    <div class="center-info"><div class="center-title-row"><h3>${escapeHTML(center.name)}</h3><span class="center-rating">✓ Verified</span></div>
    <p class="center-location">⌖ &nbsp;${escapeHTML(center.address || center.city)}</p><div class="card-tags">${ages}<span class="tag">${escapeHTML(center.hours.includes("24") ? "24/7 care" : center.hours)}</span></div>
    <div class="center-card-footer"><span class="price-from">Plans from <strong>${money(plan)}</strong> <small>${cadence}</small></span><button class="view-link" data-action="view-center" data-id="${center.id}">Meet the center ↗</button></div></div>
  </article>`;
}

async function loadCenters() {
  const city = $("#city-filter").value.trim();
  const age = $("#age-filter").value;
  const hours = $("#hours-filter").value;
  const params = new URLSearchParams();
  if (city) params.set("city", city);
  if (age) params.set("age", age);
  if (hours) params.set("hours", hours);
  const list = $("#center-list");
  list.innerHTML = `<div class="loading-card">Finding wonderful care nearby…</div>`;
  try {
    const data = await api(`/api/centers?${params}`);
    centers = data.centers;
    $("#results-count").textContent = `${centers.length} thoughtful ${centers.length === 1 ? "place" : "places"} to explore`;
    list.innerHTML = centers.length
      ? centers.map(centerCard).join("")
      : `<div class="empty-state"><strong>No centers match just yet.</strong>Try another city or loosen your filters — your next good find may be close by.</div>`;
  } catch (error) {
    list.innerHTML = `<div class="empty-state"><strong>We couldn't load centers.</strong>${escapeHTML(error.message)} <button class="view-link" data-action="retry-centers">Try again ↻</button></div>`;
  }
}

function showAuth(mode = "login", role = "parent") {
  const register = mode === "register";
  const provider = role === "provider";
  const fields = register
    ? `<div class="form-grid">
        <div class="form-field"><label for="auth-name">Your name</label><input id="auth-name" name="name" required autocomplete="name" maxlength="100"></div>
        <div class="form-field"><label for="auth-phone">Phone (optional)</label><input id="auth-phone" name="phone" autocomplete="tel"></div>
        <div class="form-field full"><label for="auth-email">Email address</label><input id="auth-email" name="email" type="email" required autocomplete="email" maxlength="254"></div>
        <div class="form-field full"><label for="auth-password">Create a password</label><input id="auth-password" name="password" type="password" minlength="10" required autocomplete="new-password"><span class="form-hint">Use at least 10 characters.</span></div>
        ${provider ? `<div class="form-field full"><label for="center-name">Childcare center name</label><input id="center-name" name="centerName" required maxlength="120"></div>
          <div class="form-field"><label for="provider-city">City</label><input id="provider-city" name="city" required maxlength="100"></div>
          <div class="form-field"><label for="provider-address">Neighborhood / address</label><input id="provider-address" name="address" required maxlength="200"></div>
          <div class="form-field full"><label for="provider-hours">Operating hours</label><input id="provider-hours" name="hours" placeholder="e.g. Open 24 hours or 6 AM – 11 PM" maxlength="80"></div>
          <div class="form-field"><label for="provider-capacity">Child capacity</label><input id="provider-capacity" name="capacity" type="number" min="1" max="1000" value="12" required></div>
          <div class="form-field"><label for="provider-certs">Safety certifications</label><input id="provider-certs" name="certifications" placeholder="Separate with commas"></div>
          <div class="form-field full"><label>Age groups served</label><div class="checkboxes">${ageCheckboxes()}</div></div>
          <div class="form-field full"><label for="provider-description">A little about your center</label><textarea id="provider-description" name="description" maxlength="1000"></textarea></div>
          <p class="form-hint full">Your provider account and center stay pending until an administrator reviews your application. Never enter children's medical or identity documents here.</p>` : ""}
      </div>`
    : `<div class="form-grid"><div class="form-field full"><label for="auth-email">Email address</label><input id="auth-email" name="email" type="email" required autocomplete="email" maxlength="254"></div><div class="form-field full"><label for="auth-password">Password</label><input id="auth-password" name="password" type="password" required autocomplete="current-password"></div></div>`;
  const content = `<form id="auth-form" data-mode="${mode}" data-role="${role}">${fields}<div class="form-error" id="form-error"></div><div class="form-actions"><button class="button button-green" type="submit">${register ? provider ? "Apply as a provider" : "Create account" : "Log in"} <span>↗</span></button><button class="form-switch" type="button" data-action="auth-switch" data-mode="${register ? "login" : "register"}">${register ? "Already with us? Log in" : "New to Nestcare? Join us"}</button></div></form>
    ${!register ? `<div class="demo-box"><strong>Try the demo</strong><br>Admin: admin@nestcare.local / NestcareAdmin123!<br>Provider: provider@nestcare.local / NestcareProvider123!<br>Create a parent account to try booking.</div>` : `<div class="form-actions"><button class="form-switch" type="button" data-action="auth-role" data-role="${provider ? "parent" : "provider"}">${provider ? "Looking for childcare? Create a parent account" : "Run a childcare center? Apply as a provider"}</button></div>`}`;
  showModal(register ? (provider ? "Grow your care community." : "A little peace of mind starts here.") : "Welcome back.", register ? (provider ? "Tell us about your center. Our team reviews every provider application." : "Create an account to find, book, and manage care.") : "Sign in to your Nestcare space.", content, { eyebrow: register ? "LET'S GET TO KNOW YOU" : "YOUR NESTCARE" });
}

function ageCheckboxes(selected = []) {
  return ["Infant", "Toddler", "Preschool"].map((age) =>
    `<label><input type="checkbox" name="ageGroups" value="${age}" ${selected.includes(age) ? "checked" : ""}>${age}</label>`
  ).join("");
}

function showCenter(center) {
  const caregiverList = center.caregivers.length
    ? `<div class="caregiver-list">${center.caregivers.map((person) => `<div class="caregiver"><span class="caregiver-avatar">${escapeHTML(person.name.slice(0, 1))}</span><span><strong>${escapeHTML(person.name)}</strong><small>${escapeHTML(person.role)} · ${escapeHTML(person.experience)}</small></span></div>`).join("")}</div>`
    : `<p>Caregiver profiles are being added by this center.</p>`;
  const plans = ["hourly", "daily", "monthly"].filter((key) => center.plans?.[key] != null)
    .map((key) => `<div class="plan-row"><span>${key[0].toUpperCase() + key.slice(1)} care</span><strong>${money(center.plans[key])}${key === "hourly" ? " / hour" : key === "daily" ? " / day" : " / month"}</strong></div>`).join("");
  const certs = center.certifications.length ? center.certifications.map((cert) => `<span class="tag">${escapeHTML(cert)}</span>`).join(" ") : `<span class="form-hint">Certification details are being reviewed.</span>`;
  showModal(center.name, `${center.address} · ${center.hours}`, `<div class="detail-cover cover-${center.id % 3 + 1}"><span class="cover-sun"></span><span class="cover-tree"></span><span class="cover-house"></span></div>
    <p class="modal-subtitle">${escapeHTML(center.description)}</p><div class="detail-section"><h3>Care plans · transparent pricing</h3>${plans}</div>
    <div class="detail-section"><h3>Little ones welcome</h3><div class="card-tags">${center.age_groups.map((age) => `<span class="tag">${escapeHTML(age)}</span>`).join("")}</div></div>
    <div class="detail-section"><h3>Caregivers</h3>${caregiverList}</div>
    <div class="detail-section"><h3>Safety & certifications</h3><div class="card-tags">${certs}</div></div>
    <p class="safety-note">Center verification is a starting point for your own decision. Ask the center questions and arrange a visit before care begins.</p>
    <div class="detail-actions">${center.plans?.hourly != null ? `<button class="button button-outline" data-action="start-booking" data-id="${center.id}" data-plan="hourly">Hourly · ${money(center.plans.hourly)}</button>` : ""}${center.plans?.daily != null ? `<button class="button button-green" data-action="start-booking" data-id="${center.id}" data-plan="daily">Request a day · ${money(center.plans.daily)}</button>` : ""}${center.plans?.monthly != null ? `<button class="button button-outline" data-action="start-booking" data-id="${center.id}" data-plan="monthly">Monthly · ${money(center.plans.monthly)}</button>` : ""}</div>`,
  { wide: true, eyebrow: "VERIFIED CHILDCARE CENTER" });
}

function showBooking(centerId, plan = "daily") {
  const center = centers.find((item) => item.id === Number(centerId));
  if (!currentUser) { closeModal(); showAuth("login"); toast("Sign in to request a childcare booking."); return; }
  if (currentUser.role !== "parent") { toast("Parent accounts can request childcare.", true); return; }
  if (!center) { toast("This center is not available.", true); return; }
  const isMonthly = plan === "monthly";
  const content = `<form id="booking-form" data-center="${center.id}" data-plan="${isMonthly ? "monthly" : plan}" data-monthly="${isMonthly}">
    <div class="form-grid">
      <div class="form-field full"><label for="child-name">Child's first name</label><input id="child-name" name="childName" required maxlength="100"></div>
      <div class="form-field"><label for="child-age">Age group</label><select id="child-age" name="childAge" required>${center.age_groups.map((age) => `<option>${escapeHTML(age)}</option>`).join("")}</select></div>
      <div class="form-field"><label for="care-date">${isMonthly ? "Start date" : "Care date"}</label><input id="care-date" name="${isMonthly ? "startDate" : "date"}" type="date" required min="${new Date().toISOString().slice(0, 10)}"></div>
      ${!isMonthly ? `<div class="form-field"><label for="booking-plan">Plan</label><select id="booking-plan" name="plan"><option value="daily" ${plan === "daily" ? "selected" : ""}>Daily · ${money(center.plans.daily || 0)}</option><option value="hourly" ${plan === "hourly" ? "selected" : ""}>Hourly · ${money(center.plans.hourly || 0)}/hr</option></select></div>
        <div class="form-field hourly-time hidden"><label for="start-time">Starts</label><input id="start-time" name="startTime" type="time"></div>
        <div class="form-field hourly-time hidden"><label for="end-time">Ends</label><input id="end-time" name="endTime" type="time"></div>` : `<div class="form-field"><label>Plan</label><input value="Monthly · ${money(center.plans.monthly || 0)} / month" disabled></div>`}
      <div class="form-field full"><label for="booking-notes">Anything you'd like the center to know? <span class="form-hint">(optional)</span></label><textarea id="booking-notes" name="notes" maxlength="500"></textarea></div>
    </div>    <button class="button button-outline button-small" type="button" data-action="check-availability">Check availability</button><span class="form-hint" id="availability-result" aria-live="polite"></span>
    <p class="form-hint">The center will confirm your request. Availability is checked again when you submit.</p>
    <div class="form-error" id="form-error"></div><div class="form-actions"><button class="button button-green" type="submit">Send ${isMonthly ? "monthly care" : "booking"} request ↗</button></div></form>`;
  showModal(isMonthly ? "Settle into a routine." : "Let's find your moment.", `${center.name} · ${center.city}`, content, { eyebrow: isMonthly ? "MONTHLY CARE" : "FLEXIBLE CARE REQUEST" });
  const planSelect = $("#booking-plan");
  if (planSelect) {
    planSelect.addEventListener("change", updateHourlyFields);
    updateHourlyFields();
  }
}

function updateHourlyFields() {
  const hourly = $("#booking-plan")?.value === "hourly";
  $$(".hourly-time").forEach((field) => field.classList.toggle("hidden", !hourly));
  $("#start-time")?.toggleAttribute("required", Boolean(hourly));
  $("#end-time")?.toggleAttribute("required", Boolean(hourly));
}

function metric(label, value) { return `<div class="metric-card"><span>${escapeHTML(label)}</span><strong>${escapeHTML(value)}</strong></div>`; }
function emptyTable(message) { return `<div class="empty-state">${escapeHTML(message)}</div>`; }

function bookingRows(bookings, role) {
  if (!bookings.length) return emptyTable("No booking requests yet.");
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Care & family</th><th>Schedule</th><th>Plan</th><th>Status</th><th>Next step</th></tr></thead><tbody>${bookings.map((item) => {
    const date = item.date === item.end_date ? dateLabel(item.date) : `${dateLabel(item.date)} – ${dateLabel(item.end_date)}`;
    const person = role === "parent" ? item.center_name : `${item.child_name} · ${item.parent_name}`;
    const actions = role === "provider" && item.status === "pending"
      ? `<button class="button button-green" data-action="booking-status" data-id="${item.id}" data-status="confirmed">Accept</button><button class="button button-danger" data-action="booking-status" data-id="${item.id}" data-status="rejected">Decline</button>`
      : role === "parent" ? `${["pending", "confirmed"].includes(item.status) ? `<button class="button button-danger" data-action="booking-status" data-id="${item.id}" data-status="cancelled">Cancel</button>` : ""}<button class="button button-outline" data-action="report-concern" data-id="${item.id}">Report concern</button>` : "—";
    return `<tr><td><strong>${escapeHTML(person)}</strong><br>${role === "parent" ? escapeHTML(item.child_name) : escapeHTML(item.center_name)}</td><td>${date}${item.start_time ? `<br>${escapeHTML(item.start_time)}–${escapeHTML(item.end_time)}` : ""}</td><td>${escapeHTML(item.plan)}</td><td>${statusPill(item.status)}</td><td><div class="table-actions">${actions}</div></td></tr>`;
  }).join("")}</tbody></table></div>`;
}

function subscriptionRows(items, role) {
  if (!items.length) return emptyTable("No monthly care requests yet.");
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Center & child</th><th>Start date</th><th>Status</th><th>Next step</th></tr></thead><tbody>${items.map((item) => {
    const person = role === "parent" ? item.center_name : `${item.child_name} · ${item.parent_name}`;
    const actions = role === "provider" && item.status === "pending"
      ? `<button class="button button-green" data-action="subscription-status" data-id="${item.id}" data-status="active">Accept</button><button class="button button-danger" data-action="subscription-status" data-id="${item.id}" data-status="rejected">Decline</button>`
      : role === "parent" && ["pending", "active"].includes(item.status)
        ? `<button class="button button-danger" data-action="subscription-status" data-id="${item.id}" data-status="cancelled">Cancel</button>` : "—";
    return `<tr><td><strong>${escapeHTML(person)}</strong><br>${role === "parent" ? escapeHTML(item.child_name) : escapeHTML(item.center_name)}</td><td>${dateLabel(item.start_date)}</td><td>${statusPill(item.status)}</td><td><div class="table-actions">${actions}</div></td></tr>`;
  }).join("")}</tbody></table></div>`;
}

function adminTables(data) {
  const centers = data.centers.map((center) => `<tr><td><strong>${escapeHTML(center.name)}</strong><br>${escapeHTML(center.city)} · ${escapeHTML(center.provider_name)}</td><td>${escapeHTML(center.hours)}</td><td>${center.certifications.map(escapeHTML).join(", ") || "No certifications listed"}</td><td>${statusPill(center.verified ? "active" : "pending")}</td><td>${center.verified ? "Verified" : `<button class="button button-green" data-action="center-verify" data-id="${center.id}" data-verified="true">Verify</button> <button class="button button-danger" data-action="center-verify" data-id="${center.id}" data-verified="false">Decline</button>`}</td></tr>`).join("");
  const users = data.users.map((user) => `<tr><td><strong>${escapeHTML(user.name)}</strong><br>${escapeHTML(user.email)}</td><td>${escapeHTML(user.role)}</td><td>${statusPill(user.status)}</td><td>${user.status === "pending" ? `<button class="button button-green" data-action="user-status" data-id="${user.id}" data-status="active">Approve</button> <button class="button button-danger" data-action="user-status" data-id="${user.id}" data-status="rejected">Decline</button>` : "—"}</td></tr>`).join("");
  const disputes = data.disputes.map((item) => `<tr><td><strong>${escapeHTML(item.center_name)}</strong><br>${escapeHTML(item.reporter_name)} · ${escapeHTML(item.child_name)}</td><td>${escapeHTML(item.message)}</td><td>${statusPill(item.status)}</td><td>${item.status === "open" ? `<button class="button button-green" data-action="dispute-status" data-id="${item.id}" data-status="resolved">Resolve</button>` : "—"}</td></tr>`).join("");
  const feedback = data.feedback.map((item) => `<tr><td>${"★".repeat(item.rating)}${"☆".repeat(5 - item.rating)}</td><td>${escapeHTML(item.category)}</td><td>${escapeHTML(item.message)}</td><td>${escapeHTML(item.created_at)}</td></tr>`).join("");
  return `<div class="dashboard-block"><h3>Center verification</h3><p class="dashboard-subtitle">Review provider applications and the safety information they supplied.</p>${centers.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Center & provider</th><th>Hours</th><th>Certifications listed</th><th>Status</th><th>Review</th></tr></thead><tbody>${centers}</tbody></table></div>` : emptyTable("No center applications yet.")}</div>
  <div class="dashboard-block"><h3>Account approvals</h3>${users.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Review</th></tr></thead><tbody>${users}</tbody></table></div>` : emptyTable("No user accounts to review.")}</div>
  <div class="dashboard-block"><h3>Family concerns</h3><p class="dashboard-subtitle">Follow up on reports from families. Keep private details within the admin team.</p>${disputes.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Booking</th><th>Concern</th><th>Status</th><th>Action</th></tr></thead><tbody>${disputes}</tbody></table></div>` : emptyTable("No family concerns have been reported.")}</div>
  <div class="dashboard-block"><h3>App feedback</h3><p class="dashboard-subtitle">Feedback is private to administrators. Avoid sharing children’s personal or medical details.</p>${feedback.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Rating</th><th>Topic</th><th>Feedback</th><th>Received</th></tr></thead><tbody>${feedback}</tbody></table></div>` : emptyTable("No app feedback has been received.")}</div>`;
}

function providerEditor(center) {
  if (!center) return `<div class="dashboard-block">${emptyTable("Your center details will appear here after an administrator approves your provider application.")}</div>`;
  return `<div class="dashboard-block"><h3>Center details & availability</h3><p class="dashboard-subtitle">Keep care hours, capacity, age groups, pricing, and caregiver introductions up to date.</p>
    <form class="dashboard-form" id="center-editor"><div class="form-grid">
      <div class="form-field full"><label>Center name</label><input value="${escapeHTML(center.name)}" disabled></div>
      <div class="form-field"><label for="center-hours">Operating hours</label><input id="center-hours" name="hours" value="${escapeHTML(center.hours)}" maxlength="80" required></div>
      <div class="form-field"><label for="center-capacity">Capacity</label><input id="center-capacity" name="capacity" type="number" value="${center.capacity}" min="1" max="1000" required></div>
      <div class="form-field full"><label>Description</label><textarea name="description" maxlength="1000">${escapeHTML(center.description)}</textarea></div>
      <div class="form-field full"><label>Age groups</label><div class="checkboxes">${ageCheckboxes(center.age_groups)}</div></div>
      <div class="form-field full"><label for="center-certifications">Certifications and safety standards <span class="form-hint">(comma separated)</span></label><input id="center-certifications" name="certifications" value="${escapeHTML(center.certifications.join(", "))}"></div>
      <div class="form-field"><label for="plan-hourly">Hourly price (₹)</label><input id="plan-hourly" name="hourly" type="number" min="0" value="${center.plans.hourly ?? 0}" required></div>
      <div class="form-field"><label for="plan-daily">Daily price (₹)</label><input id="plan-daily" name="daily" type="number" min="0" value="${center.plans.daily ?? 0}" required></div>
      <div class="form-field"><label for="plan-monthly">Monthly price (₹)</label><input id="plan-monthly" name="monthly" type="number" min="0" value="${center.plans.monthly ?? 0}" required></div>
      <div class="form-field full"><label for="center-caregivers">Caregiver profiles <span class="form-hint">(one per line: Name | Role | Experience)</span></label><textarea id="center-caregivers" name="caregivers" placeholder="Meera Iyer | Lead caregiver | 8 years">${center.caregivers.map((x) => `${x.name} | ${x.role} | ${x.experience}`).join("\n")}</textarea></div>
    </div><button class="button button-green" type="submit">Save center updates ↗</button></form></div>`;
}

async function loadDashboard() {
  if (!currentUser) return;
  $("#dashboard").classList.remove("hidden");
  $("#dashboard-title").textContent = `${currentUser.name.split(" ")[0]}'s ${currentUser.role === "parent" ? "care space" : currentUser.role === "provider" ? "provider space" : "admin overview"}`;
  const content = $("#dashboard-content");
  if (currentUser.status === "pending") {
    content.innerHTML = `<div class="safety-note">${currentUser.role === "provider" ? "Your provider application and center are saved and waiting for administrator verification. Provider management will become available after approval." : "Your account is saved and waiting for administrator approval. You’ll be able to request and manage care once it’s approved."} You can sign in any time to check this status.</div>`;
    return;
  }
  try {
    if (currentUser.role === "parent") {
      const [bookingData, subscriptionData, notificationData] = await Promise.all([
        api("/api/bookings"), api("/api/subscriptions"), api("/api/notifications")
      ]);
      const unread = notificationData.notifications.filter((note) => !note.read);
      content.innerHTML = `<div class="dashboard-grid">${metric("Booking requests", bookingData.bookings.length)}${metric("Monthly care plans", subscriptionData.subscriptions.length)}${metric("Updates", unread.length)}${metric("Care choices", "Flexible")}</div>
        ${unread.length ? `<div class="dashboard-block"><h3>Latest updates</h3><div class="notification-list">${unread.slice(0, 3).map((x) => `<div class="notification-item">${escapeHTML(x.message)}<small>${escapeHTML(x.created_at)}</small></div>`).join("")}</div><button class="view-link" data-action="read-notifications">Mark all as read</button></div>` : ""}
        <div class="dashboard-block"><h3>Your booking requests</h3>${bookingRows(bookingData.bookings, "parent")}</div><div class="dashboard-block"><h3>Monthly care</h3>${subscriptionRows(subscriptionData.subscriptions, "parent")}</div><div class="safety-note">Nestcare does not collect payments. Discuss pricing and arrangements directly with your verified childcare center.</div>`;
    } else if (currentUser.role === "provider") {
      const [analytics, centerData, bookingData, subscriptionData] = await Promise.all([
        api("/api/provider/analytics"), api("/api/provider/center"), api("/api/bookings"), api("/api/subscriptions")
      ]);
      content.innerHTML = `<div class="dashboard-grid">${metric("Centers", analytics.centers)}${metric("Booking requests", analytics.bookings)}${metric("Awaiting your reply", analytics.pending)}${metric("Booked capacity", `${analytics.utilization}%`)}</div>
        <div class="provider-layout"><div>${providerEditor(centerData.center)}</div><div><div class="dashboard-block"><h3>Care requests</h3>${bookingRows(bookingData.bookings, "provider")}</div><div class="dashboard-block"><h3>Monthly plans</h3>${subscriptionRows(subscriptionData.subscriptions, "provider")}</div></div></div>`;
    } else {
      const [overview, bookings, subscriptions] = await Promise.all([
        api("/api/admin/overview"), api("/api/bookings"), api("/api/subscriptions")
      ]);
      content.innerHTML = `<div class="dashboard-grid">${metric("Families", overview.stats.parents)}${metric("Verified providers", overview.stats.providers)}${metric("Awaiting review", overview.stats.pending)}${metric("Bookings", overview.stats.bookings)}</div>
        ${adminTables(overview)}<div class="dashboard-block"><h3>Platform bookings</h3>${bookingRows(bookings.bookings, "admin")}</div><div class="dashboard-block"><h3>Monthly subscriptions</h3>${subscriptionRows(subscriptions.subscriptions, "admin")}</div>`;
    }
  } catch (error) {
    content.innerHTML = `<div class="empty-state"><strong>We couldn't load your dashboard.</strong>${escapeHTML(error.message)}<br><button class="view-link" data-action="refresh-dashboard">Try again ↻</button></div>`;
  }
}

function showNotifications() {
  if (!currentUser) { showAuth("login"); return; }
  api("/api/notifications").then(async (data) => {
    showModal("A little update.", "Your recent Nestcare notifications.", data.notifications.length
      ? `<div class="notification-list">${data.notifications.map((note) => `<div class="notification-item">${escapeHTML(note.message)}<small>${escapeHTML(note.created_at)}</small></div>`).join("")}</div><button class="button button-outline modal-cta" data-action="read-notifications">Mark all as read</button>`
      : `<div class="empty-state">You're all caught up.</div>`);
    await api("/api/notifications/read", { method: "POST", body: {} });
  }).catch((error) => toast(error.message, true));
}

function showConcern(bookingId) {
  showModal("We're listening.", "Tell our admin team what happened. Please don't include medical details or sensitive documents.", `<form id="concern-form" data-booking="${bookingId}"><div class="form-field"><label for="concern-message">Your concern</label><textarea id="concern-message" name="message" maxlength="1000" required></textarea></div><div class="form-error" id="form-error"></div><div class="form-actions"><button class="button button-green" type="submit">Send securely ↗</button></div></form>`, { eyebrow: "FAMILY SUPPORT" });
}

$("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  loadCenters();
  $("#centers").scrollIntoView({ behavior: "smooth" });
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button, [data-action]");
  if (!button) return;
  if (button.hasAttribute("data-close-modal")) { closeModal(); return; }
  const action = button.dataset.action;
  try {
    if (button.id === "sign-in-button") showAuth("login");
    else if (button.id === "join-button") showAuth("register");
    else if (button.id === "provider-link" || button.id === "footer-provider") {
      if (currentUser?.role === "provider") {
        $("#dashboard").scrollIntoView({ behavior: "smooth" });
      } else showAuth("register", "provider");
    } else if (button.id === "dashboard-button") {
      await loadDashboard();
      $("#dashboard").scrollIntoView({ behavior: "smooth" });
    } else if (button.id === "notifications-button") showNotifications();
    else if (button.id === "logout-button") {
      await api("/api/logout", { method: "POST", body: {} });
      currentUser = null;
      accountChanged();
      $("#dashboard").classList.add("hidden");
      $("#dashboard-content").innerHTML = "";
      toast("You are signed out.");
    }
    else if (button.id === "dashboard-refresh" || action === "refresh-dashboard") await loadDashboard();
    else if (action === "view-center") {
      const center = centers.find((item) => item.id === Number(button.dataset.id));
      if (center) showCenter(center);
    } else if (action === "start-booking") showBooking(button.dataset.id, button.dataset.plan || "daily");
    else if (action === "auth-switch") showAuth(button.dataset.mode, $("#auth-form").dataset.role);
    else if (action === "auth-role") showAuth("register", button.dataset.role);
    else if (action === "retry-centers") await loadCenters();
    else if (action === "read-notifications") {
      await api("/api/notifications/read", { method: "POST", body: {} });
      closeModal();
      await loadDashboard();
      toast("You're all caught up.");
    } else if (action === "report-concern") showConcern(button.dataset.id);
    else if (action === "check-availability") {
      const form = $("#booking-form");
      const dateField = form?.querySelector('[name="date"], [name="startDate"]');
      const plan = form?.dataset.monthly === "true" ? "monthly" : $("#booking-plan")?.value;
      const params = new URLSearchParams({
        centerId: form.dataset.center,
        date: dateField?.value || "",
        plan: plan || "daily"
      });
      if (plan === "hourly") {
        params.set("startTime", $("#start-time").value);
        params.set("endTime", $("#end-time").value);
      }
      const result = $("#availability-result");
      if (!dateField?.value) {
        result.textContent = "Choose a care date first.";
      } else {
        result.textContent = "Checking…";
        const availability = await api(`/api/availability?${params}`);
        result.textContent = availability.available
          ? `${availability.availableSlots} place${availability.availableSlots === 1 ? "" : "s"} available on this date.`
          : "This date is full. Try another date or center.";
      }
    }
    else if (action === "booking-status" || action === "subscription-status") {
      const route = action === "booking-status" ? "bookings" : "subscriptions";
      const result = await api(`/api/${route}/${button.dataset.id}`, { method: "PATCH", body: { status: button.dataset.status } });
      toast(result.message);
      await loadDashboard();
    } else if (action === "center-verify") {
      const result = await api(`/api/admin/centers/${button.dataset.id}`, { method: "PATCH", body: { verified: button.dataset.verified === "true" } });
      toast(result.message);
      await loadDashboard();
    } else if (action === "user-status" || action === "dispute-status") {
      const route = action === "user-status" ? "users" : "disputes";
      const result = await api(`/api/admin/${route}/${button.dataset.id}`, { method: "PATCH", body: { status: button.dataset.status } });
      toast(result.message);
      await loadDashboard();
    }
  } catch (error) { toast(error.message, true); }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  event.preventDefault();
  const submit = $("button[type=submit]", form);
  if (submit) submit.disabled = true;
  const errorBox = $("#form-error", form);
  if (errorBox) errorBox.textContent = "";
  try {
    const values = new FormData(form);
    const mode = form.dataset.mode;
    if (form.id === "auth-form") {
      const body = Object.fromEntries(values.entries());
      if (mode === "register" && form.dataset.role === "provider") {
        body.role = "provider";
        body.capacity = Number(body.capacity);
        body.ageGroups = values.getAll("ageGroups");
        body.certifications = (body.certifications || "").split(",").map((x) => x.trim()).filter(Boolean);
      } else if (mode === "register") body.role = "parent";
      const result = await api(mode === "register" ? "/api/register" : "/api/login", { method: "POST", body });
      if (mode === "register" && form.dataset.role === "provider") {
        showModal("Application received.", result.message, `<p class="safety-note">You can log in to check your application status. We’ll review your center details before listing it for families.</p><div class="form-actions"><button class="button button-green" data-close-modal>Sounds good</button></div>`, { eyebrow: "THANK YOU" });
      } else {
        currentUser = result.user;
        accountChanged();
        closeModal();
        await loadDashboard();
        $("#dashboard").scrollIntoView({ behavior: "smooth" });
        toast(mode === "register" ? "Your account is awaiting administrator approval." : `Welcome back, ${currentUser.name.split(" ")[0]}.`);
      }
    } else if (form.id === "booking-form") {
      const isMonthly = form.dataset.monthly === "true";
      const body = Object.fromEntries(values.entries());
      body.centerId = Number(form.dataset.center);
      if (isMonthly) {
        await api("/api/subscriptions", { method: "POST", body });
      } else {
        body.plan = $("#booking-plan").value;
        if (body.plan !== "hourly") { delete body.startTime; delete body.endTime; }
        await api("/api/bookings", { method: "POST", body });
      }
      closeModal();
      toast(isMonthly ? "Monthly care request sent." : "Booking request sent.");
      await loadDashboard();
      $("#dashboard").scrollIntoView({ behavior: "smooth" });
    } else if (form.id === "concern-form") {
      const result = await api("/api/disputes", { method: "POST", body: { bookingId: Number(form.dataset.booking), message: values.get("message") } });
      closeModal();
      toast(result.message);
      await loadDashboard();
    } else if (form.id === "center-editor") {
      const caregivers = String(values.get("caregivers") || "").split("\n").map((line) => {
        const [name, role, experience] = line.split("|").map((x) => x.trim());
        return { name, role, experience };
      }).filter((person) => person.name || person.role || person.experience);
      const body = {
        hours: values.get("hours"),
        capacity: Number(values.get("capacity")),
        description: values.get("description"),
        ageGroups: values.getAll("ageGroups"),
        certifications: String(values.get("certifications")).split(",").map((x) => x.trim()).filter(Boolean),
        plans: { hourly: Number(values.get("hourly")), daily: Number(values.get("daily")), monthly: Number(values.get("monthly")) },
        caregivers
      };
      const result = await api("/api/provider/center", { method: "PATCH", body });
      toast(result.message);
      await loadCenters();
      await loadDashboard();
    }
  } catch (error) {
    if (errorBox) errorBox.textContent = error.message;
    else toast(error.message, true);
  } finally {
    if (submit?.isConnected) submit.disabled = false;
  }
});

loadUser().catch((error) => toast(error.message, true));
loadCenters();
