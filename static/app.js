document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-password-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.passwordToggle);
      if (!input) return;
      const showing = input.type === 'password';
      input.type = showing ? 'text' : 'password';
      button.setAttribute('aria-pressed', String(showing));
      button.setAttribute('aria-label', showing ? 'Hide password' : 'Show password');
      button.title = showing ? 'Hide password' : 'Show password';
    });
  });

  const canvas = document.getElementById('studyChart');
  if (canvas && window.Chart) {
    const labels = JSON.parse(canvas.dataset.labels);
    const minutes = JSON.parse(canvas.dataset.minutes);
    new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [{ data: minutes, backgroundColor: '#dcd5ff', hoverBackgroundColor: '#7357df', borderRadius: 5, maxBarThickness: 24 }] },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.raw} minutes` } } },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { color: '#9696a7', font: { size: 10 } } },
          y: { beginAtZero: true, grid: { color: '#f0eff5' }, border: { display: false }, ticks: { color: '#a2a2b0', font: { size: 9 }, callback: v => `${v}m` } }
        }
      }
    });
  }

  const timer = document.querySelector('[data-timer]');
  const activeStudyStart = document.body.dataset.activeStudyStart || timer?.dataset.start;
  if (activeStudyStart) {
    const started = new Date(activeStudyStart);
    const normalTitle = document.title;
    const update = () => {
      const pausedAtValue = timer?.dataset.pausedAt || document.body.dataset.activeStudyPausedAt;
      const pausedAt = pausedAtValue ? new Date(pausedAtValue).getTime() : Date.now();
      const pausedSeconds = Number(timer?.dataset.pausedSeconds || document.body.dataset.activeStudyPausedSeconds || 0);
      const seconds = Math.max(0, Math.floor((pausedAt - started.getTime()) / 1000) - pausedSeconds);
      const elapsed = [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60]
        .map(n => String(n).padStart(2, '0')).join(':');
      if (timer) timer.textContent = elapsed;
      document.title = `${elapsed} | ${normalTitle}`;
    };
    update();
    setInterval(update, 1000);
  }

  const dateInput = document.querySelector('input[name="test_date"]');
  if (dateInput && !dateInput.value) dateInput.value = new Date().toISOString().slice(0, 10);

  document.querySelectorAll('input[type="file"][data-size-limit]').forEach(input => {
    const feedback = input.parentElement.querySelector('[data-file-size-error]');
    const limit = Number(input.dataset.sizeLimit);
    const validateSize = () => {
      const total = [...input.files].reduce((sum, file) => sum + file.size, 0);
      const valid = total <= limit;
      input.classList.toggle('is-invalid', !valid);
      if (feedback) feedback.hidden = valid;
      return valid;
    };
    input.addEventListener('change', validateSize);
    input.form?.addEventListener('submit', event => {
      if (!validateSize()) event.preventDefault();
    });
  });

  document.querySelectorAll('.progress-form').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    const select = form.querySelector('select[name="status"]');
    const statusLabel = form.querySelector('[data-topic-status]');
    const formData = new FormData(form);
    select.disabled = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!response.ok) throw new Error('Could not save topic progress');
      const result = await response.json();
      const wasDone = statusLabel.textContent.trim() === 'Done';
      const isDone = result.status === 'completed';
      statusLabel.textContent = { not_started: 'To do', in_progress: 'Learning', completed: 'Done' }[result.status];
      const subjectProgress = document.querySelector('[data-subject-progress]');
      if (subjectProgress && wasDone !== isDone) {
        const total = Number(subjectProgress.dataset.total);
        const done = Number(subjectProgress.dataset.done) + (isDone ? 1 : -1);
        subjectProgress.dataset.done = done;
        subjectProgress.textContent = `${done}/${total} DONE`;
      }
    } catch {
      form.submit();
    } finally {
      select.disabled = false;
    }
  }));

  const pyqAttempted = document.querySelector('[data-pyq-attempted]');
  const pyqCorrect = document.querySelector('[data-pyq-correct]');
  const pyqReviewCount = document.querySelector('[data-pyq-review-count]');
  const updatePyqReviewCount = () => {
    if (!pyqAttempted || !pyqCorrect || !pyqReviewCount) return;
    const attempted = Number(pyqAttempted.value);
    const correct = Number(pyqCorrect.value);
    pyqReviewCount.textContent = attempted > 0 && correct >= 0 && correct <= attempted
      ? `Questions to review: ${attempted - correct}`
      : 'Questions to review: enter valid totals';
  };
  pyqAttempted?.addEventListener('input', updatePyqReviewCount);
  pyqCorrect?.addEventListener('input', updatePyqReviewCount);
  updatePyqReviewCount();

  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  const voiceStatus = document.querySelector('[data-voice-status]');
  document.querySelectorAll('[data-voice-target]').forEach(button => button.addEventListener('click', () => {
    if (!Speech) {
      if (voiceStatus) voiceStatus.textContent = 'Voice dictation is not supported in this browser. Try Chrome or Edge.';
      return;
    }
    const field = document.querySelector(`[name="${button.dataset.voiceTarget}"]`);
    const recognition = new Speech();
    recognition.lang = 'en-IN';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    button.classList.add('is-listening');
    button.title = 'Listening';
    if (voiceStatus) voiceStatus.textContent = 'Listening. Speak now.';
    recognition.onresult = event => {
      const words = event.results[0][0].transcript;
      field.value = `${field.value}${field.value.trim() ? ' ' : ''}${words}`;
      field.dispatchEvent(new Event('input', { bubbles: true }));
      if (voiceStatus) voiceStatus.textContent = 'Dictation added. Review or edit it before saving.';
    };
    recognition.onerror = () => {
      if (voiceStatus) voiceStatus.textContent = 'Could not capture speech. Check microphone permission and try again.';
    };
    recognition.onend = () => {
      button.classList.remove('is-listening');
      button.title = 'Start dictation';
    };
    recognition.start();
  }));

  const imageInput = document.querySelector('input[name="images"]');
  const preview = document.querySelector('[data-image-preview]');
  const mistakeForm = imageInput?.form;
  const pasteZone = document.querySelector('[data-image-paste-zone]');
  const pasteStatus = document.querySelector('[data-image-paste-status]');
  if (imageInput && preview && mistakeForm) {
    const renderImagePreview = () => {
      preview.querySelectorAll('img').forEach(image => URL.revokeObjectURL(image.src));
      preview.replaceChildren();
      [...imageInput.files].forEach(file => {
        if (!file.type.startsWith('image/')) return;
        const image = document.createElement('img');
        image.src = URL.createObjectURL(file);
        image.alt = file.name;
        image.title = file.name;
        preview.append(image);
      });
    };
    imageInput.addEventListener('change', renderImagePreview);

    const addPastedImages = files => {
      const supported = files.filter(file => ['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type));
      if (!supported.length) return false;
      try {
        const transfer = new DataTransfer();
        [...imageInput.files].forEach(file => transfer.items.add(file));
        supported.forEach((file, index) => {
          const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif' }[file.type];
          transfer.items.add(new File([file], `mistake-snip-${Date.now()}-${index + 1}.${extension}`, { type: file.type }));
        });
        imageInput.files = transfer.files;
        imageInput.dispatchEvent(new Event('change', { bubbles: true }));
        if (pasteStatus) pasteStatus.textContent = `${supported.length} screenshot${supported.length === 1 ? '' : 's'} added. Check the preview, then save your mistake.`;
      } catch {
        if (pasteStatus) pasteStatus.textContent = 'This browser could not attach the pasted screenshot. Use Choose File to select a saved image instead.';
      }
      return true;
    };

    document.addEventListener('paste', event => {
      if (!mistakeForm.isConnected) return;
      const items = [...(event.clipboardData?.items || [])];
      const images = items.filter(item => item.kind === 'file' && item.type.startsWith('image/')).map(item => item.getAsFile()).filter(Boolean);
      if (!images.length) return;
      event.preventDefault();
      addPastedImages(images);
    });

    if (pasteZone) {
      pasteZone.addEventListener('click', () => pasteZone.focus());
      pasteZone.addEventListener('dragover', event => {
        event.preventDefault();
        pasteZone.classList.add('is-dragging');
      });
      pasteZone.addEventListener('dragleave', () => pasteZone.classList.remove('is-dragging'));
      pasteZone.addEventListener('drop', event => {
        event.preventDefault();
        pasteZone.classList.remove('is-dragging');
        addPastedImages([...event.dataTransfer.files]);
      });
    }
  }
});
