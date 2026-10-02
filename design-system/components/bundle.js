/* @ds-bundle: {"format":4,"namespace":"Shadcn","components":[{"name":"Button"},{"name":"Badge"},{"name":"Input"},{"name":"Textarea"},{"name":"Label"},{"name":"Card"},{"name":"Alert"},{"name":"Checkbox"},{"name":"Switch"},{"name":"Tabs"},{"name":"Avatar"},{"name":"Separator"},{"name":"Skeleton"},{"name":"Progress"},{"name":"Kbd"}]} */
(function () {
  var React = window.React;
  var h = React.createElement;
  function cn() {
    var out = [];
    for (var i = 0; i < arguments.length; i++) if (arguments[i]) out.push(arguments[i]);
    return out.join(" ");
  }
  function omit(p, keys) {
    var o = {};
    for (var k in p) if (keys.indexOf(k) < 0) o[k] = p[k];
    return o;
  }
  function simple(tag, base, slot) {
    return function (p) {
      return h(tag, Object.assign({ "data-slot": slot }, omit(p, ["className"]), { className: cn(base, p.className) }));
    };
  }
  function useControllable(value, defaultValue, onChange) {
    var s = React.useState(defaultValue);
    var controlled = value !== undefined;
    var cur = controlled ? value : s[0];
    function set(v) { if (!controlled) s[1](v); if (onChange) onChange(v); }
    return [cur, set];
  }

  function Button(p) {
    var variant = p.variant || "default", size = p.size || "default";
    var rest = omit(p, ["variant", "size", "className", "asChild"]);
    var tag = p.href ? "a" : "button";
    return h(tag, Object.assign({ "data-slot": "button", "data-variant": variant, "data-size": size }, rest, {
      className: cn("sc-btn", "sc-btn--" + variant, size !== "default" && "sc-btn--" + size, p.className)
    }));
  }
  function Badge(p) {
    var variant = p.variant || "default";
    return h("span", Object.assign({ "data-slot": "badge" }, omit(p, ["variant", "className"]), {
      className: cn("sc-badge", "sc-badge--" + variant, p.className)
    }));
  }
  function Input(p) {
    return h("input", Object.assign({ "data-slot": "input" }, omit(p, ["className"]), { className: cn("sc-input", p.className) }));
  }
  function Textarea(p) {
    return h("textarea", Object.assign({ "data-slot": "textarea" }, omit(p, ["className"]), { className: cn("sc-input", p.className) }));
  }
  var Label = simple("label", "sc-label", "label");

  var Card = simple("div", "sc-card", "card");
  var CardHeader = simple("div", "sc-card-header", "card-header");
  var CardTitle = simple("div", "sc-card-title", "card-title");
  var CardDescription = simple("div", "sc-card-description", "card-description");
  var CardContent = simple("div", "sc-card-content", "card-content");
  var CardFooter = simple("div", "sc-card-footer", "card-footer");

  function Alert(p) {
    var variant = p.variant || "default";
    return h("div", Object.assign({ role: "alert", "data-slot": "alert" }, omit(p, ["variant", "className"]), {
      className: cn("sc-alert", variant === "destructive" && "sc-alert--destructive", p.className)
    }));
  }
  var AlertTitle = simple("div", "sc-alert-title", "alert-title");
  var AlertDescription = simple("div", "sc-alert-description", "alert-description");

  var check = h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 3, strokeLinecap: "round", strokeLinejoin: "round" }, h("path", { d: "M20 6 9 17l-5-5" }));
  function Checkbox(p) {
    var st = useControllable(p.checked, !!p.defaultChecked, p.onCheckedChange);
    var rest = omit(p, ["checked", "defaultChecked", "onCheckedChange", "className"]);
    return h("button", Object.assign({ type: "button", role: "checkbox", "aria-checked": st[0], "data-slot": "checkbox",
      "data-state": st[0] ? "checked" : "unchecked", onClick: function () { st[1](!st[0]); } }, rest, {
      className: cn("sc-checkbox", p.className) }), st[0] ? check : null);
  }
  function Switch(p) {
    var st = useControllable(p.checked, !!p.defaultChecked, p.onCheckedChange);
    var rest = omit(p, ["checked", "defaultChecked", "onCheckedChange", "className"]);
    return h("button", Object.assign({ type: "button", role: "switch", "aria-checked": st[0], "data-slot": "switch",
      "data-state": st[0] ? "checked" : "unchecked", onClick: function () { st[1](!st[0]); } }, rest, {
      className: cn("sc-switch", p.className) }), h("span", { className: "sc-switch-thumb", "data-slot": "switch-thumb" }));
  }

  var TabsCtx = React.createContext(null);
  function Tabs(p) {
    var st = useControllable(p.value, p.defaultValue, p.onValueChange);
    return h(TabsCtx.Provider, { value: st }, h("div", Object.assign({ "data-slot": "tabs" },
      omit(p, ["value", "defaultValue", "onValueChange", "className"]), { className: cn("sc-tabs", p.className) })));
  }
  function TabsList(p) {
    return h("div", Object.assign({ role: "tablist", "data-slot": "tabs-list" }, omit(p, ["className"]), { className: cn("sc-tabs-list", p.className) }));
  }
  function TabsTrigger(p) {
    var st = React.useContext(TabsCtx), active = st && st[0] === p.value;
    return h("button", Object.assign({ type: "button", role: "tab", "aria-selected": active, "data-slot": "tabs-trigger",
      "data-state": active ? "active" : "inactive", onClick: function () { st && st[1](p.value); } },
      omit(p, ["value", "className"]), { className: cn("sc-tabs-trigger", p.className) }));
  }
  function TabsContent(p) {
    var st = React.useContext(TabsCtx);
    if (!st || st[0] !== p.value) return null;
    return h("div", Object.assign({ role: "tabpanel", "data-slot": "tabs-content", "data-state": "active" },
      omit(p, ["value", "className"]), { className: cn("sc-tabs-content", p.className) }));
  }

  var Avatar = simple("span", "sc-avatar", "avatar");
  function AvatarImage(p) {
    var s = React.useState(false);
    if (s[0] || !p.src) return null;
    return h("img", Object.assign({ "data-slot": "avatar-image", onError: function () { s[1](true); } },
      omit(p, ["className"]), { className: cn("sc-avatar-image", p.className) }));
  }
  var AvatarFallback = simple("span", "sc-avatar-fallback", "avatar-fallback");

  function Separator(p) {
    var o = p.orientation || "horizontal";
    return h("div", Object.assign({ role: p.decorative === false ? "separator" : "none", "data-slot": "separator", "data-orientation": o },
      omit(p, ["orientation", "decorative", "className"]), { className: cn("sc-separator", p.className) }));
  }
  var Skeleton = simple("div", "sc-skeleton", "skeleton");
  function Progress(p) {
    var v = Math.max(0, Math.min(100, p.value || 0));
    return h("div", Object.assign({ role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": v, "data-slot": "progress" },
      omit(p, ["value", "className"]), { className: cn("sc-progress", p.className) }),
      h("div", { className: "sc-progress-indicator", "data-slot": "progress-indicator", style: { transform: "translateX(-" + (100 - v) + "%)" } }));
  }
  var Kbd = simple("kbd", "sc-kbd", "kbd");

  window.Shadcn = {
    cn: cn,
    Button: Button, Badge: Badge, Input: Input, Textarea: Textarea, Label: Label,
    Card: Card, CardHeader: CardHeader, CardTitle: CardTitle, CardDescription: CardDescription, CardContent: CardContent, CardFooter: CardFooter,
    Alert: Alert, AlertTitle: AlertTitle, AlertDescription: AlertDescription,
    Checkbox: Checkbox, Switch: Switch,
    Tabs: Tabs, TabsList: TabsList, TabsTrigger: TabsTrigger, TabsContent: TabsContent,
    Avatar: Avatar, AvatarImage: AvatarImage, AvatarFallback: AvatarFallback,
    Separator: Separator, Skeleton: Skeleton, Progress: Progress, Kbd: Kbd
  };
})();
