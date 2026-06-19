(function () {
    'use strict';

    var playerTeamMap   = (typeof statPlayerTeamMap  !== 'undefined') ? statPlayerTeamMap  : {};
    var homeTeamId      = (typeof statHomeTeamId     !== 'undefined') ? String(statHomeTeamId) : null;
    var awayTeamId      = (typeof statAwayTeamId     !== 'undefined') ? String(statAwayTeamId) : null;
    // Prior GF/GA per team: totals from every game this season/division
    // EXCEPT tonight's, computed server-side. GA already accounts for all
    // opponents across the team's games, so it is correct in a multi-team
    // division. Tonight's goals are added live from the form below.
    var statPriorVals   = (typeof statPrior !== 'undefined') ? statPrior
        : { home_gf: 0, home_ga: 0, away_gf: 0, away_ga: 0 };

    // ── Team autofill ─────────────────────────────────────────────────────

    function autofillTeam(playerSelect) {
        var m = playerSelect.name.match(/^stat_set-(\d+)-player$/);
        if (!m) return;
        var teamSelect = document.querySelector('select[name="stat_set-' + m[1] + '-team"]');
        if (!teamSelect) return;
        var playerId = playerSelect.value;
        if (playerId && playerTeamMap[playerId]) {
            teamSelect.value = playerTeamMap[playerId];
        }
    }

    // ── Goal counting ─────────────────────────────────────────────────────

    function computeGoalTotals() {
        var totals = {};
        if (homeTeamId) totals[homeTeamId] = 0;
        if (awayTeamId) totals[awayTeamId] = 0;

        document.querySelectorAll('[name^="stat_set-"][name$="-goals"]').forEach(function (input) {
            var m = input.name.match(/^stat_set-(\d+)-goals$/);
            if (!m) return;
            // Exclude rows the user has marked for deletion.
            var del = document.querySelector('[name="stat_set-' + m[1] + '-DELETE"]');
            if (del && del.checked) return;
            var teamSel = document.querySelector('[name="stat_set-' + m[1] + '-team"]');
            if (!teamSel || !teamSel.value) return;
            var tid = String(teamSel.value);
            var goals = parseInt(input.value, 10) || 0;
            if (Object.prototype.hasOwnProperty.call(totals, tid)) {
                totals[tid] += goals;
            }
        });

        return totals;
    }

    function readField(name) {
        var el = document.querySelector('[name="' + name + '"]');
        return el ? (parseInt(el.value, 10) || 0) : 0;
    }

    // ── GF/GA auto-fill ───────────────────────────────────────────────────
    //
    // Suggested value = (this stat from all prior games this season)
    //                 + (tonight's goals currently in the form)
    //
    // For GF, "prior games" is the team's own goals; for GA it is the goals
    // scored by every opponent in the team's games. Both come pre-computed
    // from the server (statPrior), so tonight's matchup is never double-counted.
    //
    // When the suggestion matches or exceeds the stored value, auto-fill the
    // input so GF/GA stay in sync as player stats are entered.
    //
    // Guard: if the suggestion is LOWER than the stored value, some past games
    // have no player stats entered yet — the higher stored value is more
    // accurate, so we warn instead of overwriting.

    function applyFieldUpdate(spanId, inputName, priorGames, formTonight) {
        var span = document.getElementById(spanId);
        var input = document.querySelector('[name="' + inputName + '"]');
        if (!span) return;

        var currentVal = input ? (parseInt(input.value, 10) || 0) : 0;
        var suggested  = priorGames + formTonight;

        if (suggested < currentVal) {
            // Stats on record add up to less than the stored value — this means
            // some past games were entered without player stats. Don't overwrite;
            // warn the user so they know why the numbers don't match.
            span.innerHTML =
                '⚠ Player stats total <strong>' + suggested + '</strong> goals this season' +
                ' (' + priorGames + ' from prior games + ' + formTonight + ' tonight),' +
                ' but this field is set to <strong>' + currentVal + '</strong>.' +
                ' Some past games may be missing player stats—the higher value is likely correct.';
            span.style.color = '#92400e';
            span.style.display = 'block';
            return;
        }

        // Stats account for the stored value: auto-fill and clear any warning.
        if (input && suggested !== currentVal) {
            input.value = suggested;
        }
        span.style.display = 'none';
    }

    function updateSuggestions() {
        if (!homeTeamId || !awayTeamId) return;
        var totals = computeGoalTotals();
        var homeTonight = totals[homeTeamId] || 0;
        var awayTonight = totals[awayTeamId] || 0;

        // GF = own goals tonight; GA = tonight's opponent's goals.
        // (Home's opponent tonight is the away team, and vice versa.)
        applyFieldUpdate('home-gf-suggestion', 'home_stat-goals_for',
            statPriorVals.home_gf, homeTonight);
        applyFieldUpdate('away-gf-suggestion', 'away_stat-goals_for',
            statPriorVals.away_gf, awayTonight);
        applyFieldUpdate('home-ga-suggestion', 'home_stat-goals_against',
            statPriorVals.home_ga, awayTonight);
        applyFieldUpdate('away-ga-suggestion', 'away_stat-goals_against',
            statPriorVals.away_ga, homeTonight);
    }

    // ── Player select: Select2 for mobile-friendly search ─────────────────
    //
    // The player dropdown in each stat row can hold 20-40 names. Native
    // mobile pickers are scroll-only; Select2 adds a search box.
    // Select2 is already on the page (loaded by dal for the goalie fields),
    // so we just apply it to player selects. Initialization runs on `load`
    // to match dal's timing and guarantee django.jQuery.fn.select2 exists.
    // New rows added via "Add another Stat" are handled via the jQuery
    // `formset:added` event that Django admin fires on the inline group.

    function applySelect2ToPlayerSelect(selectEl) {
        var jq = window.django && window.django.jQuery;
        if (!jq || !jq.fn || !jq.fn.select2) return;
        // Skip if already initialized.
        if (jq(selectEl).data('select2')) return;
        jq(selectEl).select2({
            width: '100%',
            placeholder: 'Search players…',
            allowClear: true,
        });
    }

    function applySelect2ToAllPlayerSelects() {
        document.querySelectorAll(
            'select[name^="stat_set-"][name$="-player"]'
        ).forEach(applySelect2ToPlayerSelect);
    }

    // ── Shootout section show/hide ─────────────────────────────────────────
    //
    // The shootout section only appears for non-postseason games (rendered
    // conditionally by the template). Show it whenever either team has an
    // OTW value greater than zero, and hide it otherwise.

    function updateShootoutVisibility() {
        var section = document.getElementById('shootout-section');
        if (!section) return;
        var homeOtwEl = document.querySelector('[name="home_stat-otw"]');
        var awayOtwEl = document.querySelector('[name="away_stat-otw"]');
        var homeOtw = homeOtwEl ? (parseInt(homeOtwEl.value, 10) || 0) : 0;
        var awayOtw = awayOtwEl ? (parseInt(awayOtwEl.value, 10) || 0) : 0;
        section.style.display = (homeOtw > 0 || awayOtw > 0) ? 'flex' : 'none';
    }

    document.addEventListener('DOMContentLoaded', function () {
        updateSuggestions();
        updateShootoutVisibility();
    });

    window.addEventListener('load', function () {
        applySelect2ToAllPlayerSelects();

        // Django admin triggers `formset:added` via jQuery on the inline
        // group when the user clicks "Add another Stat". Listen at the
        // document level so bubbling catches it regardless of DOM structure.
        var jq = window.django && window.django.jQuery;
        if (jq) {
            jq(document).on('formset:added', function (event, $row, formsetName) {
                if (formsetName !== 'stat_set') return;
                var sel = $row.find('select[name$="-player"]')[0];
                if (sel) applySelect2ToPlayerSelect(sel);
            });
        }
    });

    // ── Event delegation ──────────────────────────────────────────────────

    document.addEventListener('change', function (e) {
        if (e.target.tagName !== 'SELECT' && e.target.tagName !== 'INPUT') return;
        var name = e.target.name || '';
        if (/^stat_set-\d+-player$/.test(name)) {
            autofillTeam(e.target);
            updateSuggestions();
        } else if (/^stat_set-\d+-team$/.test(name) || /^stat_set-\d+-goals$/.test(name) || /^stat_set-\d+-DELETE$/.test(name)) {
            updateSuggestions();
        } else if (name === 'home_stat-otw' || name === 'away_stat-otw') {
            updateShootoutVisibility();
        }
    });

    document.addEventListener('input', function (e) {
        var name = e.target.name || '';
        if (/^stat_set-\d+-goals$/.test(name)) {
            updateSuggestions();
        } else if (name === 'home_stat-otw' || name === 'away_stat-otw') {
            updateShootoutVisibility();
        }
    });
})();
