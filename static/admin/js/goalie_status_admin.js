(function() {
    function handleStatusChange(statusSelect) {
        var row = statusSelect.closest('tr');
        if (!row) {
            return;
        }
        var isAway = statusSelect.name.indexOf('away_goalie_status') !== -1;
        var goalieSelectName = isAway ? 'away_goalie' : 'home_goalie';
        var goalieSelect = row.querySelector('select[name$="' + goalieSelectName + '"]');
        if (!goalieSelect) {
            return;
        }
        var rosterGoalieId = goalieSelect.getAttribute('data-roster-goalie-id') || '';
        if (statusSelect.value === '2') {
            goalieSelect.value = '';
            return;
        }
        if (statusSelect.value === '3' && !goalieSelect.value && rosterGoalieId) {
            goalieSelect.value = rosterGoalieId;
        }
    }

    function initRow(row) {
        var statusSelects = row.querySelectorAll('select[name$="away_goalie_status"], select[name$="home_goalie_status"]');
        statusSelects.forEach(function(select) {
            select.addEventListener('change', function() {
                handleStatusChange(select);
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        var rows = document.querySelectorAll('#result_list tbody tr');
        rows.forEach(initRow);
    });
})();
