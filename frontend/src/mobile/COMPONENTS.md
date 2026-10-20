# Mobile runtime components

## Carousel

`Carousel` is the standard component for horizontal collections: cards, images, media, swipeable items, and chip or filter rails. Place it directly inside `MobileScroll`; consumers should not add gesture wrappers or pointer handlers.

```tsx
<MobileScroll>
  <section>
    <Carousel
      ariaLabel="Event details"
      className="event-carousel"
      contentClassName="event-carousel-track"
    >
      {cards}
    </Carousel>
  </section>
</MobileScroll>
```

The runtime resolves nested gestures by axis. Horizontal intent stays with `Carousel`; vertical intent is handed to the parent `MobileScroll`. Slight vertical drift after a horizontal gesture is claimed does not move, rubber-band, or add momentum to the parent. Taps remain clickable, while a completed drag suppresses the item click.

Do not use `data-scroll-drag="ignore"` for carousels or ordinary rails. It is a hard opt-out that prevents parent scrolling in every direction. Do not layer CSS scroll snapping over the runtime's JavaScript release motion.

For one-card-at-a-time collections, enable `paging`. A swipe advances at most one page and short drags settle back. The default remains free scrolling. Size each child to the viewport in app CSS. Optional zero-based `pageIndex` and `onPageChange` props connect page buttons or dots; the component clamps the page when children are removed and realigns on resize. A focused paged carousel also supports Left/Right arrow keys. Reduced-motion preferences disable its page animation.

```tsx
<Carousel paging pageIndex={page} onPageChange={setPage} ariaLabel="Reminders">
  {cards}
</Carousel>
```

## Keyboard-linked surfaces

Use `KeyboardInput`, `KeyboardTextarea`, or `MobileTextField` for all text entry. Position a composer, search surface, or other keyboard-linked UI from `useKeyboardInsets().bottomInset`. The inset is relative to the app viewport: Android's closed-keyboard viewport already ends above its navigation bar, while iOS still needs its overlaid home-indicator inset; both platforms return the keyboard height while the keyboard is open. Never pin those surfaces to only `keyboardHeight`. When that surface closes, call `keyboard.hide()` in the same event before updating its own open state.

## BottomSheet

`BottomSheet` dismisses the keyboard before opening and animates both in and out by default. Keep its `open` state controlled through `onOpenChange`; no consumer exit-animation wrapper is needed.
