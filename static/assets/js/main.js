/*
	Halcyonic by HTML5 UP
	html5up.net | @ajlkn
	Free for personal and commercial use under the CCA 3.0 license (html5up.net/license)
*/

(function($) {

	skel
		.breakpoints({
			desktop: '(min-width: 737px)',
			tablet: '(min-width: 737px) and (max-width: 1200px)',
			mobile: '(max-width: 736px)'
		})
		.viewport({
			breakpoints: {
				tablet: {
					width: 1080
				}
			}
		});

	$(function() {

		var $window = $(window),
			$body = $('body');

		// Fix: Placeholder polyfill.
			$('form').placeholder();

		// Prioritize "important" elements on mobile.
			skel.on('+mobile -mobile', function() {
				$.prioritize(
					'.important\\28 mobile\\29',
					skel.breakpoint('mobile').active
				);
			});

		// Off-Canvas Navigation.

			// Title Bar.
				$(
					'<div id="titleBar">' +
						'<a href="#navPanel" class="toggle"></a>' +
						'<a href="/"><span class="title">' + $('#logo').html() + '</span></a>' +
					'</div>'
				)
					.appendTo($body);

			// Navigation Panel.
				$(
					'<div id="navPanel">' +
						'<nav>' +
							$('#nav').navList() +
						'</nav>' +
					'</div>'
				)
					.appendTo($body)
					.panel({
						delay: 500,
						hideOnClick: true,
						hideOnSwipe: true,
						resetScroll: true,
						resetForms: true,
						side: 'left',
						target: $body,
						visibleClass: 'navPanel-visible'
					});

			// Fix: Remove navPanel transitions on WP<10 (poor/buggy performance).
				if (skel.vars.os == 'wp' && skel.vars.osVersion < 10)
					$('#titleBar, #navPanel, #page-wrapper')
						.css('transition', 'none');

		// Image Modal Functionality
		const images = document.querySelectorAll('.resizable-image');
		const modal = document.createElement('div');
		const modalImg = document.createElement('img');
		const closeBtn = document.createElement('span');

		modal.className = 'image-modal';
		modalImg.className = 'image-modal-content';
		closeBtn.className = 'close-modal';
		closeBtn.innerHTML = '&times;';

		modal.appendChild(modalImg);
		modal.appendChild(closeBtn);
		document.body.appendChild(modal);

		images.forEach(image => {
			image.addEventListener('click', function() {
				modal.style.display = 'block';
				modalImg.src = this.src;
			});
		});

		closeBtn.addEventListener('click', function() {
			modal.style.display = 'none';
		});

		modal.addEventListener('click', function(e) {
			if (e.target !== modalImg) {
				modal.style.display = 'none';
			}
		});

	});

})(jQuery);
function handleTeam(url) {
    window.location.href = url;
}

function togglePlayersTable(id) {
    var playersTable = document.getElementById("playerstatsection-"+id);
    var showall = playersTable.className.includes("shorttable");
    playersTable.className = showall ? "longtable" : "shorttable";
}
