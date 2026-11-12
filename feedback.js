const form = document.querySelector("#feedback-form");
const status = document.querySelector("#feedback-status");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  status.textContent = "Sending…";
  status.classList.remove("is-error");
  try {
    const values = new FormData(form);
    const response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rating: Number(values.get("rating")),
        category: values.get("category"),
        message: values.get("message")
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Feedback could not be sent. Please try again.");
    form.reset();
    status.textContent = data.message;
  } catch (error) {
    status.textContent = error.message || "Feedback could not be sent. Please try again.";
    status.classList.add("is-error");
  } finally {
    submit.disabled = false;
  }
});
