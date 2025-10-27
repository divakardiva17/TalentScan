document.addEventListener("DOMContentLoaded", function () {
  const resumeInput = document.getElementById("resumeInput");
  if (resumeInput) {
    resumeInput.addEventListener("change", function (e) {
      const f = e.target.files[0];
      if (f) {
        document.getElementById("fileHelp").textContent = `${f.name} (${Math.round(f.size / 1024)} KB)`;
      } else {
        document.getElementById("fileHelp").textContent = "Max 8 MB. Supported: PDF, DOCX.";
      }
    });
  }
});