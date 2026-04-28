(function () {
    'use strict';

    var playerTeamMap   = (typeof statPlayerTeamMap  !== 'undefined') ? statPlayerTeamMap  : {};
    var homeTeamId      = (typeof statHomeTeamId     !== 'undefined') ? String(statHomeTeamId) : null;
    var awayTeamId      = (typeof statAwayTeamId     !== 'undefined') ? String(statAwayTeamId) : null;
    // Goals already committed to the DB for this specific game (per team).
    var tonightSaved    = (typeof statTonightSaved   !== 'undefined') ? statTonightSaved   : { home: 0, away: 0 };
    // Sum of all Stat.goals this season/division for each team (all games, from DB).
    var seasonGoals     = (typeof statSeasonGoals    !== 'undefined') ? statSeasonGoals    : { home: 0, away: 0 };

    // Baselines are the GF/GA values present in the form at page load.
    var baseline = {};

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

    // ── Suggestion logic ──────────────────────────────────────────────────
    //
    // Suggested GF = (season goals from all Stat records)
    //              - (tonight's goals already saved in DB)
    //              + (tonight's goals currently in the form)
    //
    // This stays correct on re-visits: the saved goals cancel out so they
    // aren't counted twice, and edits in the form are reflected live.
    //
    // Guard: if season stats < current GF, previous games are missing stats
    // and any suggestion would be wrong — hide it silently.

    function setSuggestion(spanId, seasonStat, savedTonight, formTonight, currentVal) {
        var span = document.getElementById(spanId);
        if (!span) return;

        if (seasonStat < currentVal) {
            // Stats are incomplete for prior games; suggestion would mislead.
            span.style.display = 'none';
            return;
        }

        var adjustedBaseline = seasonStat - savedTonight;
        var suggested = adjustedBaseline + formTonight;

        if (suggested === currentVal) {
            span.style.display = 'none';
            return;
        }

        span.textContent = 'Suggested: ' + suggested +
            ' (' + adjustedBaseline + ' + ' + formTonight + ' tonight)';
        span.style.display = 'block';
    }

    function updateSuggestions() {
        if (!homeTeamId || !awayTeamId) return;
        var totals = computeGoalTotals();
        var homeTonight = totals[homeTeamId] || 0;
        var awayTonight = totals[awayTeamId] || 0;

        // GF = own goals
        setSuggestion('home-gf-suggestion',
            seasonGoals.home, tonightSaved.home, homeTonight, baseline.homeGF);
        setSuggestion('away-gf-suggestion',
            seasonGoals.away, tonightSaved.away, awayTonight, baseline.awayGF);

        // GA = opponent's goals
        setSuggestion('home-ga-suggestion',
            seasonGoals.away, tonightSaved.away, awayTonight, baseline.homeGA);
        setSuggestion('away-ga-suggestion',
            seasonGoals.home, tonightSaved.home, homeTonight, baseline.awayGA);
    }

    // ── Initialisation ────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', function () {
        var read = function (name) {
            var el = document.querySelector('[name="' + name + '"]');
            return el ? (parseInt(el.value, 10) || 0) : 0;
        };
        baseline.homeGF = read('home_stat-goals_for');
        baseline.homeGA = read('home_stat-goals_against');
        baseline.awayGF = read('away_stat-goals_for');
        baseline.awayGA = read('away_stat-goals_against');

        updateSuggestions();
    });

    // ── Event delegation ──────────────────────────────────────────────────

    document.addEventListener('change', function (e) {
        if (e.target.tagName !== 'SELECT' && e.target.tagName !== 'INPUT') return;
        var name = e.target.name || '';
        if (/^stat_set-\d+-player$/.test(name)) {
            autofillTeam(e.target);
            updateSuggestions();
        } else if (/^stat_set-\d+-team$/.test(name) || /^stat_set-\d+-goals$/.test(name)) {
            updateSuggestions();
        }
    });

    document.addEventListener('input', function (e) {
        if (/^stat_set-\d+-goals$/.test(e.target.name || '')) {
            updateSuggestions();
        }
    });
})();
