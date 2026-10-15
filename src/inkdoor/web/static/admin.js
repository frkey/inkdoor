// inkdoor admin: small enhancements. Every page works without this file.
// The Content-Security-Policy forbids inline scripts and handlers, so behavior is attached here
// to elements marked with data attributes:
//   form[data-confirm]      asks before submitting (remove buttons)
//   form[data-test-target]  runs a link test in the background and shows the result in the
//                           element with that id; data-error is shown when the test cannot run
(function () {
  "use strict";

  var FRAGMENT_HEADER = "X-Inkdoor-Fragment";

  function confirmBeforeSubmit(form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    });
  }

  function showError(target, form) {
    var box = document.createElement("div");
    var line = document.createElement("p");
    box.className = "test-result";
    line.className = "result-line result-fail";
    line.textContent = form.getAttribute("data-error") || "";
    box.appendChild(line);
    target.textContent = "";  // not replaceChildren: missing in Safari before 14
    target.appendChild(box);
  }

  function testInBackground(form) {
    var target = document.getElementById(form.getAttribute("data-test-target"));
    if (!target || !window.fetch || !window.FormData) {
      return;  // the form posts normally and the page comes back with the result
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = form.querySelector("button[type=submit]");
      var label = button ? button.textContent : "";
      if (button) {
        button.disabled = true;
        button.textContent = button.getAttribute("data-busy-label") || label;
      }
      target.setAttribute("aria-busy", "true");

      function done() {
        target.removeAttribute("aria-busy");
        if (button) {
          button.disabled = false;
          button.textContent = label;
        }
      }

      function failed() {
        try {
          showError(target, form);
        } catch (ignored) {
          // the button must come back even if the message cannot be drawn
        }
      }

      var request;
      try {
        // the CSRF token and the digest travel in the form body, like a normal submit
        request = fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          credentials: "same-origin",
          headers: { "X-Requested-With": "inkdoor" }
        });
      } catch (error) {
        failed();
        done();
        return;
      }
      request.then(function (response) {
        return response.text().then(function (text) {
          // only a result fragment is shown; an error page (e.g. an expired session) is not
          if (response.headers.get(FRAGMENT_HEADER) === "1") {
            target.innerHTML = text;
          } else {
            failed();
          }
        });
      }).then(done, function () {
        failed();
        done();
      });
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach(confirmBeforeSubmit);
  document.querySelectorAll("form[data-test-target]").forEach(testInBackground);
})();
