# 추가 합주 페이지 CSS 스타일 레퍼런스

> 출처: `pracapp/templates/pracapp/extra_practice.html`
> 저장일: 2026-02-24
> 다른 페이지 적용 시 참고용

---

## CSS 변수

```css
:root {
  --slot-h: 32px;          /* 시간 슬롯 1칸 높이 (압축 시 20px로 변경) */
  --time-col-w: 52px;      /* 좌측 시간 레이블 열 너비 */
  --ep-primary: #5b4fcf;        /* 주 색상 (인디고/바이올렛) */
  --ep-primary-light: #ede9ff;  /* 주 색상 연한 배경 */
}
```

---

## 레이아웃

```css
/* 페이지 전체 컨테이너 */
.ep-page { max-width: 1100px; margin: 0 auto; padding: 0 1rem 3rem; }
```

---

## 헤더

```css
.ep-header {
  display: flex; align-items: center; gap: 1rem;
  padding: 1rem 0 0.75rem;
  border-bottom: 2px solid var(--ep-primary);
  margin-bottom: 1rem;
  flex-wrap: wrap;
}
.ep-song-title { font-size: 1.15rem; font-weight: 700; color: var(--ep-primary); }
.ep-song-artist { font-size: 0.85rem; color: #666; margin-left: 0.3rem; }
.ep-back-btn { margin-left: auto; font-size: 0.85rem; }
```

---

## 주 네비게이션

```css
.ep-week-nav {
  display: flex; align-items: center; gap: 0.75rem;
  margin-bottom: 1rem;
}
.ep-week-label { font-weight: 600; font-size: 0.95rem; min-width: 200px; text-align: center; }
```

---

## 합주실 탭

```css
.ep-room-tabs {
  display: flex; flex-wrap: wrap; gap: 0.4rem;
  margin-bottom: 0.75rem; align-items: center;
}
.ep-room-tab {
  padding: 0.3rem 0.85rem; border-radius: 20px; border: 1.5px solid #ccc;
  background: #fff; font-size: 0.82rem; cursor: pointer; transition: all .15s;
}
.ep-room-tab.active {
  border-color: var(--ep-primary); background: var(--ep-primary);
  color: #fff; font-weight: 600;
}
.ep-room-tab-add { border-style: dashed; color: var(--ep-primary); }
```

---

## 보드 그리드

```css
.ep-board-wrapper { overflow-x: auto; }
.ep-board {
  display: grid;
  grid-template-columns: var(--time-col-w) repeat(7, 1fr);
  border: 1px solid #ddd; border-radius: 8px; overflow: hidden;
  min-width: 640px;
}

/* 헤더 행 */
.ep-board-head {
  background: #f4f4f8; font-weight: 600; font-size: 0.78rem;
  text-align: center; padding: 0.4rem 0.2rem; border-bottom: 1px solid #ddd;
}
.ep-board-head.today { background: #ede9ff; color: var(--ep-primary); }

/* 시간 레이블 열 */
.ep-time-col { display: flex; flex-direction: column; border-right: 1px solid #e0e0e0; }
.ep-time-slot {
  height: var(--slot-h); font-size: 0.68rem; color: #999;
  padding: 2px 4px; border-bottom: 1px solid #f0f0f0; box-sizing: border-box;
}
.ep-time-slot.half { border-bottom-color: #f8f8f8; color: transparent; }

/* 일자 열 */
.ep-day-col { position: relative; border-right: 1px solid #e8e8e8; }
.ep-day-col:last-child { border-right: none; }
.ep-day-grid { position: relative; box-sizing: border-box; }

/* 슬롯 구분선 */
.ep-slot-line {
  position: absolute; left: 0; right: 0;
  border-bottom: 1px solid #f0f0f0; pointer-events: none;
}
.ep-slot-line.half { border-bottom-color: #f8f8f8; }
```

---

## 오버레이

```css
/* 합주실 불가능 (주황 해칭) */
.ep-room-block {
  position: absolute; left: 0; right: 0;
  background: repeating-linear-gradient(
    45deg,
    rgba(245,160,50,.18) 0, rgba(245,160,50,.18) 4px,
    transparent 4px, transparent 10px
  );
  border-left: 3px solid #f5a032;
  pointer-events: none; z-index: 1;
}

/* 멤버 불가능 (빨간 해칭, hover 시 사유 표시) */
.ep-conflict-overlay {
  position: absolute; left: 0; right: 0;
  background: repeating-linear-gradient(
    135deg,
    rgba(220,50,50,.06) 0, rgba(220,50,50,.06) 4px,
    transparent 4px, transparent 10px
  );
  pointer-events: none; z-index: 1;
}
/* 사유 표시 시: pointer-events: auto; cursor: help; 추가 */
```

---

## 카드

```css
/* 기존 합주 배경 카드 (읽기 전용) */
.ep-bg-card {
  position: absolute; left: 2px; right: 2px;
  background: #e8e8ee; border: 1px solid #ccc; border-radius: 4px;
  font-size: 0.68rem; color: #666; padding: 2px 4px;
  overflow: hidden; z-index: 2; pointer-events: none;
}
.ep-bg-card.extra { background: #e4e0ff; border-color: #b0a0ff; } /* 타 곡 추가합주 */

/* 내 추가합주 카드 (편집 가능) */
.ep-my-card {
  position: absolute; left: 2px; right: 2px;
  background: var(--ep-primary-light); border: 2px solid var(--ep-primary);
  border-radius: 5px; padding: 3px 6px;
  font-size: 0.75rem; font-weight: 600; color: var(--ep-primary);
  z-index: 3; cursor: default;
  display: flex; flex-direction: column; gap: 1px;
}
.ep-my-card .ep-card-del {
  position: absolute; top: 2px; right: 3px;
  font-size: 0.7rem; cursor: pointer; color: #999; line-height: 1;
}
.ep-my-card .ep-card-del:hover { color: #c00; }

/* 드래그 배치 프리뷰 */
.ep-drag-preview {
  position: absolute; left: 2px; right: 2px;
  background: rgba(91,79,207,.25); border: 2px dashed var(--ep-primary);
  border-radius: 5px; z-index: 10; pointer-events: none; display: none;
}
.ep-drag-preview.invalid { background: rgba(200,40,40,.18); border-color: #c00; }
```

---

## 사이드 패널

```css
.ep-side-panel { margin-top: 1.25rem; }
.ep-side-title { font-size: 0.82rem; font-weight: 700; color: #444; margin-bottom: 0.5rem; }

.ep-placed-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.ep-placed-item {
  display: flex; align-items: center; justify-content: space-between;
  background: var(--ep-primary-light); border: 1.5px solid var(--ep-primary);
  border-radius: 6px; padding: 0.4rem 0.75rem; font-size: 0.82rem;
}
.ep-placed-item .ep-del-btn { font-size: 0.75rem; color: #999; cursor: pointer; border: none; background: none; }
.ep-placed-item .ep-del-btn:hover { color: #c00; }

/* 드래그 소스 카드 */
.ep-drag-source {
  display: inline-flex; align-items: center; gap: 0.5rem;
  background: var(--ep-primary); color: #fff;
  border-radius: 8px; padding: 0.5rem 1rem;
  font-size: 0.85rem; font-weight: 600; cursor: grab; user-select: none;
}
.ep-drag-source:active { cursor: grabbing; }
```

---

## 토스트

```css
#ep-toast {
  position: fixed; bottom: 1.5rem; right: 1.5rem;
  background: #333; color: #fff; padding: 0.6rem 1.1rem;
  border-radius: 8px; font-size: 0.85rem; z-index: 9999;
  opacity: 0; transition: opacity .25s; pointer-events: none;
}
#ep-toast.show { opacity: 1; }
#ep-toast.error { background: #c00; }
```

---

## 범례

```css
.ep-legend { display: flex; flex-wrap: wrap; gap: 0.75rem; font-size: 0.75rem; color: #555; margin-bottom: 0.75rem; align-items: center; }
.ep-legend-item { display: flex; align-items: center; gap: 0.3rem; }
.ep-legend-box { width: 18px; height: 14px; border-radius: 3px; flex-shrink: 0; }
```

---

## 색상 팔레트 요약

| 역할 | 색상값 |
|---|---|
| 주 색상 (인디고) | `#5b4fcf` |
| 주 색상 연한 배경 | `#ede9ff` |
| 합주실 불가 해칭 | `rgba(245,160,50,.18)` + `#f5a032` border |
| 멤버 불가 해칭 | `rgba(220,50,50,.06)` |
| 기존 합주 배경 | `#e8e8ee` / `#ccc` |
| 타 곡 추가합주 | `#e4e0ff` / `#b0a0ff` |
| 에러 토스트 | `#c00` |

---

## 적용 가이드

1. `--ep-primary` / `--ep-primary-light` 변수만 바꾸면 전체 테마 색 변경 가능
2. `--slot-h` 를 `20px` 로 줄이면 압축 보기, `32px` 이면 기본 보기
3. 보드 그리드는 `grid-template-columns: var(--time-col-w) repeat(N, 1fr)` 에서 N 을 바꾸면 열 수 조정 가능 (7일 외 다른 범위 적용 시)
4. `.ep-conflict-overlay` 에 `pointer-events: auto; cursor: help;` 추가하면 hover 툴팁 사용 가능
