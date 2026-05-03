(function () {
    'use strict';

    // ── Desktop dropdown: touch-device click-to-toggle ──────────────

    var touchDevice = false;
    document.addEventListener('touchstart', function () {
        touchDevice = true;
    }, { once: true, passive: true });

    function closeAllDesktopDropdowns() {
        document.querySelectorAll('#nav .nav-dropdown.nav-open').forEach(function (el) {
            el.classList.remove('nav-open');
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        // Desktop: on touch devices, first tap opens dropdown; second tap navigates.
        document.querySelectorAll('#nav .nav-dropdown > a').forEach(function (link) {
            link.addEventListener('click', function (e) {
                if (!touchDevice) return;
                var dropdown = this.closest('.nav-dropdown');
                var isOpen = dropdown.classList.contains('nav-open');
                closeAllDesktopDropdowns();
                if (!isOpen) {
                    dropdown.classList.add('nav-open');
                    e.preventDefault();
                }
            });
        });

        document.addEventListener('click', function (e) {
            if (!e.target.closest('#nav .nav-dropdown')) {
                closeAllDesktopDropdowns();
            }
        });

        // Mobile panel accordion — panel is created by main.js on DOMContentLoaded,
        // so we retry briefly until it exists.
        enhanceNavPanel(0);
    });

    // ── Mobile nav panel: accordion ─────────────────────────────────

    function enhanceNavPanel(attempt) {
        var panel = document.getElementById('navPanel');
        if (!panel) {
            if (attempt < 15) setTimeout(function () { enhanceNavPanel(attempt + 1); }, 80);
            return;
        }

        var links = Array.from(panel.querySelectorAll('.link'));

        links.forEach(function (link, index) {
            // Only process top-level items.
            if (link.classList.contains('depth-1')) return;

            // Collect the depth-1 items that immediately follow this item.
            var children = [];
            var i = index + 1;
            while (i < links.length && links[i].classList.contains('depth-1')) {
                children.push(links[i]);
                i++;
            }

            // No sub-items → standalone link, navigate normally.
            if (children.length === 0) return;

            // Collapse children by default.
            children.forEach(function (child) { child.style.display = 'none'; });

            // Add expand/collapse indicator to the section header.
            var indicator = document.createElement('span');
            indicator.className = 'nav-accordion-indicator';
            indicator.setAttribute('aria-hidden', 'true');
            indicator.textContent = '▾';
            link.appendChild(indicator);
            link.classList.add('nav-accordion-parent');

            link.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                var isOpen = this.classList.contains('nav-accordion-open');

                // Collapse every section first.
                panel.querySelectorAll('.nav-accordion-parent').forEach(function (p) {
                    p.classList.remove('nav-accordion-open');
                });
                panel.querySelectorAll('.link.depth-1').forEach(function (c) {
                    c.style.display = 'none';
                });

                // If it was closed, open this one.
                if (!isOpen) {
                    this.classList.add('nav-accordion-open');
                    children.forEach(function (child) {
                        child.style.display = ''; // restore CSS flex value
                    });
                }
            });
        });
    }

}());
