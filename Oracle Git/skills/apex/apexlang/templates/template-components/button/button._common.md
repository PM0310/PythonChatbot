---
templateId: button.common
componentType: templateComponent
version: 1.0
description: Shared canonical contract for the Button helper template component.
---

# Purpose

Define the shared variable contract, guardrails, and output skeleton for Theme 42 `button` helper fragments.

---

# Generation Rules (MANDATORY)

1. Use `button <staticId> ( ... )` as a helper fragment, not as page-level button metadata.
2. Keep this helper inside action-bearing template components or action groups.
3. Use `menuId` only when the parent pattern expects a menu-trigger button.
4. Keep `isHot`, `isDisabled`, and `isIconOnly` opt-in.
5. Use `iconClasses` only when the prompt requests visible icon treatment.
6. Keep helper-button attributes aligned with `button._template_options.md`.

---

# Variable Contract

| Name | Required | Type | Notes |
|------|----------|------|-------|
| buttonStaticId | yes | string | Helper block identifier. |
| label | optional | string | Visible button label. |
| behavior.target | optional | string | Navigation target. |
| menuId | optional | string | Menu identifier when acting as a trigger. |
| cssClasses | optional | string | Additional button classes. |
| iconClasses | optional | string | Leading icon classes. |
| isDisabled | optional | boolean | Disable the helper. |
| isHot | optional | boolean | Render hot styling. |
| isIconOnly | optional | boolean | Render icon-only styling. |

---

# Output Template - Full

```apx
button {{buttonStaticId}} (
    label: {{label}}
    cssClasses: {{cssClasses}}
    iconClasses: {{iconClasses}}
    menuId: {{menuId}}
    isDisabled: {{isDisabled}}
    isHot: {{isHot}}
    isIconOnly: {{isIconOnly}}
    behavior {
        target: {{behavior.target}}
    }
)
```

---

# Conditional Rendering Rules

- Render `behavior` only when the helper should navigate.
- Render `menuId` only for menu-trigger behavior.
- Avoid combining `isIconOnly: true` with a visible text label unless the parent pattern explicitly requires both.

# Validation Checklist

- The fragment starts with `button <staticId> (`.
- `menuId` is used only for menu-trigger behavior.
- Optional styling flags are included intentionally.
