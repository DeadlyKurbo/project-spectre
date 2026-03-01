const clockEl = document.getElementById("clock");
const greetingEl = document.getElementById("greeting");
const statusLine = document.getElementById("statusLine");
const form = document.getElementById("registerForm");

function updateClock() {
  const now = new Date();
  clockEl.textContent = `Server-local view: ${now.toLocaleTimeString()}`;

  const hour = now.getHours();
  const windowLabel = hour < 12 ? "Morning" : hour < 18 ? "Afternoon" : "Evening";
  const operatorName = localStorage.getItem("directorName") || "Director";
  greetingEl.textContent = `${windowLabel}, ${operatorName}.`;
}

updateClock();
setInterval(updateClock, 1000);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusLine.textContent = "Submitting operator registration...";

  const formData = new FormData(form);
  const directorPassword = formData.get("directorPassword");
  formData.delete("directorPassword");

  try {
    const response = await fetch("/api/operator/register", {
      method: "POST",
      body: formData,
      headers: {
        "x-director-password": directorPassword,
      },
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Registration failed");
    }

    statusLine.textContent = "Operator registration complete. Redirecting to security dashboard...";
    setTimeout(() => {
      window.location.href = "/director/security";
    }, 800);
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
