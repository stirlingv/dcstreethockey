(function () {
    // Build the modal overlay once, append to body when DOM is ready.
    function init() {
        var modal = document.createElement('div');
        modal.id = 'ppp-modal';
        modal.style.cssText =
            'display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);' +
            'z-index:9999;cursor:zoom-out;align-items:center;justify-content:center;';
        modal.innerHTML =
            '<img id="ppp-modal-img" style="max-width:90%;max-height:90%;' +
            'border-radius:6px;box-shadow:0 8px 32px rgba(0,0,0,.5);">';
        modal.addEventListener('click', function () {
            modal.style.display = 'none';
        });
        document.body.appendChild(modal);

        // Close on Escape key
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') modal.style.display = 'none';
        });

        // Delegate clicks on any element with data-photo-url
        document.addEventListener('click', function (e) {
            var target = e.target.closest('[data-photo-url]');
            if (!target) return;
            e.preventDefault();
            document.getElementById('ppp-modal-img').src = target.dataset.photoUrl;
            modal.style.display = 'flex';
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
