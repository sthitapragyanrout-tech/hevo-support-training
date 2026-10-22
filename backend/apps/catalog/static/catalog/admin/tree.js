// Content Node changelist — collapsible tree. Progressive enhancement:
// without this JS the page is just the flat, already-correctly-ordered
// list — nothing breaks, clicking a toggle just does nothing.
document.addEventListener("DOMContentLoaded", function () {
  var nodes = document.querySelectorAll(".tree-node");
  if (!nodes.length) return;

  var childrenOf = {};
  nodes.forEach(function (el) {
    var parentPk = el.dataset.parentPk;
    if (parentPk) {
      childrenOf[parentPk] = childrenOf[parentPk] || [];
      childrenOf[parentPk].push(el.dataset.pk);
    }
  });

  function rowForPk(pk) {
    var span = document.querySelector('.tree-node[data-pk="' + pk + '"]');
    return span ? span.closest("tr") : null;
  }

  // Hide/show the subtree under `pk`. When expanding, a descendant only
  // becomes visible if its own branch is still expanded too — collapsing
  // an ancestor and re-expanding it should restore whatever the deeper
  // toggles were set to, not force everything open.
  function setDescendantsVisible(pk, visible) {
    (childrenOf[pk] || []).forEach(function (childPk) {
      var row = rowForPk(childPk);
      if (row) row.style.display = visible ? "" : "none";
      var toggle = row && row.querySelector(".tree-toggle");
      var childExpanded = !toggle || toggle.dataset.expanded !== "false";
      setDescendantsVisible(childPk, visible && childExpanded);
    });
  }

  nodes.forEach(function (el) {
    var toggle = el.querySelector(".tree-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", function (e) {
      e.preventDefault();
      var expanded = toggle.dataset.expanded !== "false";
      toggle.dataset.expanded = expanded ? "false" : "true";
      toggle.textContent = expanded ? "▶" : "▼";
      setDescendantsVisible(el.dataset.pk, !expanded);
    });
  });
});
