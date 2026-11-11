/*
 * Game Lines / Player Props panels (partials/odds_panels.html).
 * Loaded by the Schedule page and the home page.
 */

// Show or hide one game's Game Lines or Player Props panel. The button
// reads "Hide" while its panel is open and returns to its label when closed.
function toggleOdds(btn, panelId) {
	var panel = document.getElementById(panelId);
	var expanded = btn.getAttribute('aria-expanded') === 'true';
	if (expanded) {
		panel.hidden = true;
		btn.setAttribute('aria-expanded', 'false');
		btn.textContent = btn.getAttribute('data-label');
	} else {
		if (!btn.getAttribute('data-label')) {
			btn.setAttribute('data-label', btn.textContent);
		}
		panel.hidden = false;
		btn.setAttribute('aria-expanded', 'true');
		btn.textContent = 'Hide';
	}
}

// Re-sort a Player Props panel by goal, assist or point odds. The panel
// holds one list of players; each row carries its rank in every market
// (data-goal-rank, data-assist-rank, data-point-rank), so sorting is a
// matter of putting the rows back in that order.
function showPropSort(sortKey, el) {
	var panel = el.closest('.props-panel');
	var list = panel.querySelector('.props-list');
	var rows = Array.prototype.slice.call(list.querySelectorAll('.props-row'));
	rows.sort(function(a, b) {
		return Number(a.getAttribute('data-' + sortKey + '-rank')) -
			Number(b.getAttribute('data-' + sortKey + '-rank'));
	});
	rows.forEach(function(row) { list.appendChild(row); });
	list.setAttribute('data-sort', sortKey);
	panel.querySelectorAll('.props-sort-col').forEach(function(col) {
		var key = col.getAttribute('data-sort');
		var isActive = key === sortKey;
		col.classList.toggle('props-sort-active', isActive);
		col.textContent = key.toUpperCase() + (isActive ? ' ▲' : '');
	});
}
