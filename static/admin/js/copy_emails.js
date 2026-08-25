(function () {
    function showFeedback(button, text) {
        var original = button.getAttribute('data-original-label');
        if (!original) {
            original = button.textContent;
            button.setAttribute('data-original-label', original);
        }
        button.textContent = text;
        window.setTimeout(function () {
            button.textContent = original;
        }, 1800);
    }

    function fallbackCopy(text) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        var copied = false;
        try {
            copied = document.execCommand('copy');
        } catch (err) {
            copied = false;
        }
        document.body.removeChild(textarea);
        return copied;
    }

    function handleClick(button) {
        var emails = button.getAttribute('data-emails') || '';
        if (!emails) {
            showFeedback(button, 'No emails to copy');
            return;
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(emails).then(
                function () {
                    showFeedback(button, 'Copied!');
                },
                function () {
                    showFeedback(button, fallbackCopy(emails) ? 'Copied!' : 'Copy failed — select manually');
                }
            );
        } else {
            showFeedback(button, fallbackCopy(emails) ? 'Copied!' : 'Copy failed — select manually');
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var buttons = document.querySelectorAll('.js-copy-emails');
        buttons.forEach(function (button) {
            button.addEventListener('click', function (event) {
                event.preventDefault();
                handleClick(button);
            });
        });
    });
})();
