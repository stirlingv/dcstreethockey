(function () {
    'use strict';

    var playerTeamMap = (typeof statPlayerTeamMap !== 'undefined') ? statPlayerTeamMap : {};

    function autofillTeam(playerSelect) {
        var match = playerSelect.name.match(/^stat_set-(\d+)-player$/);
        if (!match) return;
        var idx = match[1];
        var teamSelect = document.querySelector('select[name="stat_set-' + idx + '-team"]');
        if (!teamSelect) return;
        var playerId = playerSelect.value;
        if (playerId && playerTeamMap[playerId]) {
            teamSelect.value = playerTeamMap[playerId];
        }
    }

    // Event delegation: handles both existing rows and rows added via "Add another Stat".
    document.addEventListener('change', function (e) {
        if (
            e.target.tagName === 'SELECT' &&
            /^stat_set-\d+-player$/.test(e.target.name)
        ) {
            autofillTeam(e.target);
        }
    });
})();
