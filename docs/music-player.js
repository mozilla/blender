// Music player for BLEnder Mission Control
// Depends on PLAYLIST global from playlist.js

let playerAudio = null;
let playerIndex = 0;
let playerOrder = [];
let playerPlaying = false;

function shuffleArray(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
}

function loadTrack(index) {
  const track = PLAYLIST[playerOrder[index]];
  playerAudio.src = track.mp3;

  const titleEl = document.getElementById('player-title');
  const artistEl = document.getElementById('player-artist');
  const attrLink = document.getElementById('attr-link');

  titleEl.textContent = track.title;
  let credit = track.artist;
  if (track.featuring) credit += ` ft. ${track.featuring}`;
  artistEl.textContent = credit;

  attrLink.href = track.page;
  attrLink.textContent = track.license;
}

function togglePlay() {
  const btn = document.getElementById('btn-play');
  if (playerPlaying) {
    playerAudio.pause();
    playerPlaying = false;
    btn.textContent = '\u25B6';
  } else {
    playerAudio.play();
    playerPlaying = true;
    btn.textContent = '\u275A\u275A';
  }
}

function nextTrack() {
  playerIndex = (playerIndex + 1) % PLAYLIST.length;
  loadTrack(playerIndex);
  if (playerPlaying) playerAudio.play();
}

function prevTrack() {
  if (playerAudio.currentTime > 3) {
    playerAudio.currentTime = 0;
  } else {
    playerIndex = (playerIndex - 1 + PLAYLIST.length) % PLAYLIST.length;
    loadTrack(playerIndex);
    if (playerPlaying) playerAudio.play();
  }
}

// eslint-disable-next-line no-unused-vars
function initPlayer() {
  playerAudio = new Audio();
  playerAudio.volume = 0.4;

  // Fisher-Yates shuffle of playlist indices
  playerOrder = Array.from({ length: PLAYLIST.length }, (_, i) => i);
  shuffleArray(playerOrder);

  // Bind controls
  document.getElementById('btn-play').addEventListener('click', togglePlay);
  document.getElementById('btn-next').addEventListener('click', nextTrack);
  document.getElementById('btn-prev').addEventListener('click', prevTrack);

  // Auto-advance on track end
  playerAudio.addEventListener('ended', nextTrack);

  // Stop on error — don't skip to next (avoids rapid looping on 403s)
  playerAudio.addEventListener('error', () => {
    playerPlaying = false;
    document.getElementById('btn-play').textContent = '\u25B6';
  });

  // Load first track and autoplay
  loadTrack(0);
  playerAudio.play().then(() => {
    playerPlaying = true;
    document.getElementById('btn-play').textContent = '\u275A\u275A';
  }).catch(() => {
    // Browser blocked autoplay — user must click play
  });
}
