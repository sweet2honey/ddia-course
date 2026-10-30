/* 课程共享交互组件：测验 / 回忆卡 / 场景判断
   组件用法见 assets/course.js 顶部注释。全部离线可用，无依赖。 */
(function () {
  'use strict';

  /* ---- 1. 单选题 ----
     <div class="quiz">
       <p class="q">题干</p>
       <button data-ok="1" data-why="为什么对">选项 A</button>
       <button data-why="为什么错">选项 B</button>
       <p class="feedback"></p>
     </div>                                                        */
  document.querySelectorAll('.quiz').forEach(function (quiz) {
    var feedback = quiz.querySelector('.feedback');
    var buttons = quiz.querySelectorAll('button');
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var ok = btn.dataset.ok === '1';
        btn.classList.add(ok ? 'correct' : 'wrong');
        buttons.forEach(function (b) { b.disabled = true; });
        if (!ok) {
          buttons.forEach(function (b) { if (b.dataset.ok === '1') b.classList.add('correct'); });
        }
        if (feedback) {
          feedback.innerHTML =
            '<span class="verdict ' + (ok ? 'ok' : 'no') + '">' +
            (ok ? '对。' : '不对。正确答案已标绿。') +
            '</span> ' + (btn.dataset.why || '');
        }
      });
    });
  });

  /* ---- 2. 回忆卡 ----
     <div class="recall">
       <textarea></textarea>
       <button class="reveal">对照答案</button>
       <div class="answer">…</div>
     </div>                                                         */
  document.querySelectorAll('.recall').forEach(function (box) {
    var btn = box.querySelector('.reveal');
    var ans = box.querySelector('.answer');
    if (!btn || !ans) return;
    btn.addEventListener('click', function () {
      ans.classList.add('shown');
      btn.textContent = '已展开 · 再点收起';
      var open = btn.dataset.open !== '1';
      btn.dataset.open = open ? '1' : '0';
      if (!open) ans.classList.remove('shown');
    });
  });

  /* ---- 3. 场景判断 ----
     <div class="triage">
       <p class="score"></p>
       <div class="row">
         <p>场景描述</p>
         <div class="opts">
           <button data-ok="1">标签</button>
           <button>标签</button>
         </div>
         <p class="note">解释</p>
       </div>
     </div>                                                         */
  document.querySelectorAll('.triage').forEach(function (board) {
    var rows = Array.prototype.slice.call(board.querySelectorAll('.row'));
    var score = board.querySelector('.score');
    var done = 0, hits = 0;

    function paint() {
      if (!score) return;
      score.textContent = '已完成 ' + done + ' / ' + rows.length +
        (done === rows.length ? '，答对 ' + hits + ' 题。' : '。');
    }
    paint();

    rows.forEach(function (row) {
      var buttons = row.querySelectorAll('.opts button');
      var note = row.querySelector('.note');
      buttons.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var ok = btn.dataset.ok === '1';
          if (ok) hits++;
          done++;
          buttons.forEach(function (b) {
            b.disabled = true;
            if (b.dataset.ok === '1') b.classList.add('correct');
          });
          if (!ok) btn.classList.add('wrong');
          if (note) {
            note.classList.add('shown');
            if (!ok && note.dataset.hint) {
              note.textContent = note.dataset.hint + ' ' + note.textContent;
            }
          }
          paint();
        });
      });
    });
  });
})();
