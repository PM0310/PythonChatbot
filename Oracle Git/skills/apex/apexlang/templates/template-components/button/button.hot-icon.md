---
templateId: button.hot-icon
componentType: templateComponent
imports:
  - button.common
version: 1.0
description: Hot Button helper example with icon styling.
---

# Purpose
Render a Button helper with hot emphasis and a leading icon.

# Output Template
```apx
button {{buttonStaticId}} (
    label: {{label}}
    iconClasses: {{iconClasses}}
    isHot: true
)
```

# Conditional Rendering Rules
- Use `isHot: true` only when the button deserves primary emphasis.
- Render `iconClasses` only when visible icon treatment is requested.

# Validation Checklist
- The icon classes are present.
- Hot styling is used intentionally for primary emphasis.
