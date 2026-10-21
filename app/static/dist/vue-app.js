var __getOwnPropNames = Object.getOwnPropertyNames;
var __commonJS = (cb, mod) => function __require() {
  return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
};
var require_vue_app = __commonJS({
  "vue-app.js"(exports, module) {
    /**
    * @vue/shared v3.5.43
    * (c) 2018-present Yuxi (Evan) You and Vue contributors
    * @license MIT
    **/
    // @__NO_SIDE_EFFECTS__
    function makeMap(str) {
      const map = /* @__PURE__ */ Object.create(null);
      for (const key of str.split(",")) map[key] = 1;
      return (val) => val in map;
    }
    const EMPTY_OBJ = {};
    const EMPTY_ARR = [];
    const NOOP = () => {
    };
    const NO = () => false;
    const isOn = (key) => key.charCodeAt(0) === 111 && key.charCodeAt(1) === 110 && // uppercase letter
    (key.charCodeAt(2) > 122 || key.charCodeAt(2) < 97);
    const isModelListener = (key) => key.startsWith("onUpdate:");
    const extend = Object.assign;
    const remove = (arr, el) => {
      const i = arr.indexOf(el);
      if (i > -1) {
        arr.splice(i, 1);
      }
    };
    const hasOwnProperty$9 = Object.prototype.hasOwnProperty;
    const hasOwn = (val, key) => hasOwnProperty$9.call(val, key);
    const isArray$1 = Array.isArray;
    const isMap = (val) => toTypeString(val) === "[object Map]";
    const isSet = (val) => toTypeString(val) === "[object Set]";
    const isDate = (val) => toTypeString(val) === "[object Date]";
    const isFunction$1 = (val) => typeof val === "function";
    const isString = (val) => typeof val === "string";
    const isSymbol = (val) => typeof val === "symbol";
    const isObject$1 = (val) => val !== null && typeof val === "object";
    const isPromise = (val) => {
      return (isObject$1(val) || isFunction$1(val)) && isFunction$1(val.then) && isFunction$1(val.catch);
    };
    const objectToString$1 = Object.prototype.toString;
    const toTypeString = (value) => objectToString$1.call(value);
    const toRawType = (value) => {
      return toTypeString(value).slice(8, -1);
    };
    const isPlainObject$1 = (val) => toTypeString(val) === "[object Object]";
    const isIntegerKey = (key) => isString(key) && key !== "NaN" && key[0] !== "-" && "" + parseInt(key, 10) === key;
    const isReservedProp = /* @__PURE__ */ makeMap(
      // the leading comma is intentional so empty string "" is also included
      ",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"
    );
    const cacheStringFunction = (fn) => {
      const cache = /* @__PURE__ */ Object.create(null);
      return ((str) => {
        const hit = cache[str];
        return hit || (cache[str] = fn(str));
      });
    };
    const camelizeRE = /-\w/g;
    const camelize = cacheStringFunction(
      (str) => {
        return str.replace(camelizeRE, (c2) => c2.slice(1).toUpperCase());
      }
    );
    const hyphenateRE = /\B([A-Z])/g;
    const hyphenate = cacheStringFunction(
      (str) => str.replace(hyphenateRE, "-$1").toLowerCase()
    );
    const capitalize = cacheStringFunction((str) => {
      return str.charAt(0).toUpperCase() + str.slice(1);
    });
    const toHandlerKey = cacheStringFunction(
      (str) => {
        const s = str ? `on${capitalize(str)}` : ``;
        return s;
      }
    );
    const hasChanged = (value, oldValue) => !Object.is(value, oldValue);
    const invokeArrayFns = (fns, ...arg) => {
      for (let i = 0; i < fns.length; i++) {
        fns[i](...arg);
      }
    };
    const def = (obj, key, value, writable = false) => {
      Object.defineProperty(obj, key, {
        configurable: true,
        enumerable: false,
        writable,
        value
      });
    };
    const looseToNumber = (val) => {
      const n = parseFloat(val);
      return isNaN(n) ? val : n;
    };
    const toNumber = (val) => {
      const n = isString(val) ? Number(val) : NaN;
      return isNaN(n) ? val : n;
    };
    let _globalThis;
    const getGlobalThis = () => {
      return _globalThis || (_globalThis = typeof globalThis !== "undefined" ? globalThis : typeof self !== "undefined" ? self : typeof window !== "undefined" ? window : typeof global !== "undefined" ? global : {});
    };
    function normalizeStyle(value) {
      if (isArray$1(value)) {
        const res = {};
        for (let i = 0; i < value.length; i++) {
          const item = value[i];
          const normalized = isString(item) ? parseStringStyle(item) : normalizeStyle(item);
          if (normalized) {
            for (const key in normalized) {
              res[key] = normalized[key];
            }
          }
        }
        return res;
      } else if (isString(value) || isObject$1(value)) {
        return value;
      }
    }
    const listDelimiterRE = /;(?![^(]*\))/g;
    const propertyDelimiterRE = /:([^]+)/;
    const styleCommentRE = /"(?:[^"\\]|\\[^])*"|'(?:[^'\\]|\\[^])*'|\\[^]|\/\*[^]*?\*\//g;
    function parseStringStyle(cssText) {
      const ret = {};
      cssText.replace(styleCommentRE, (match) => match.startsWith("/*") ? "" : match).split(listDelimiterRE).forEach((item) => {
        if (item) {
          const tmp = item.split(propertyDelimiterRE);
          tmp.length > 1 && (ret[tmp[0].trim()] = tmp[1].trim());
        }
      });
      return ret;
    }
    function normalizeClass(value) {
      let res = "";
      if (isString(value)) {
        res = value;
      } else if (isArray$1(value)) {
        for (let i = 0; i < value.length; i++) {
          const normalized = normalizeClass(value[i]);
          if (normalized) {
            res += normalized + " ";
          }
        }
      } else if (isObject$1(value)) {
        for (const name in value) {
          if (value[name]) {
            res += name + " ";
          }
        }
      }
      return res.trim();
    }
    const specialBooleanAttrs = `itemscope,allowfullscreen,formnovalidate,ismap,nomodule,novalidate,readonly`;
    const isSpecialBooleanAttr = /* @__PURE__ */ makeMap(specialBooleanAttrs);
    function includeBooleanAttr(value) {
      return !!value || value === "";
    }
    function looseCompareArrays(a, b, seen) {
      if (a.length !== b.length) return false;
      let equal = true;
      for (let i = 0; equal && i < a.length; i++) {
        equal = looseEqual(a[i], b[i], seen);
      }
      return equal;
    }
    function looseCompareCollections(a, b, seen) {
      if (a.size !== b.size) return false;
      const candidates = Array.from(b);
      const matched = new Uint8Array(candidates.length);
      for (const item of a) {
        let index = -1;
        for (let i = 0; i < candidates.length; i++) {
          if (!matched[i] && looseEqual(item, candidates[i], seen)) {
            index = i;
            break;
          }
        }
        if (index < 0) return false;
        matched[index] = 1;
      }
      return true;
    }
    function looseCompareObjects(a, b, seen) {
      let aValidType = isMap(a);
      let bValidType = isMap(b);
      if (aValidType || bValidType) {
        return aValidType && bValidType ? looseCompareCollections(a, b, seen) : false;
      }
      aValidType = isSet(a);
      bValidType = isSet(b);
      if (aValidType || bValidType) {
        return aValidType && bValidType ? looseCompareCollections(a, b, seen) : false;
      }
      const aKeysCount = Object.keys(a).length;
      const bKeysCount = Object.keys(b).length;
      if (aKeysCount !== bKeysCount) {
        return false;
      }
      for (const key in a) {
        const aHasKey = a.hasOwnProperty(key);
        const bHasKey = b.hasOwnProperty(key);
        if (aHasKey && !bHasKey || !aHasKey && bHasKey || !looseEqual(a[key], b[key], seen)) {
          return false;
        }
      }
      return String(a) === String(b);
    }
    function looseCompareNested(a, b, seen, compare) {
      if (!seen) {
        seen = [/* @__PURE__ */ new Map(), /* @__PURE__ */ new Map()];
      }
      const [seenA, seenB] = seen;
      if (seenA.has(a) || seenB.has(b)) {
        return seenA.get(a) === b && seenB.get(b) === a;
      }
      seenA.set(a, b);
      seenB.set(b, a);
      const equal = compare(a, b, seen);
      seenA.delete(a);
      seenB.delete(b);
      return equal;
    }
    function looseEqual(a, b, seen) {
      if (a === b) return true;
      let aValidType = isDate(a);
      let bValidType = isDate(b);
      if (aValidType || bValidType) {
        return aValidType && bValidType ? a.getTime() === b.getTime() : false;
      }
      aValidType = isSymbol(a);
      bValidType = isSymbol(b);
      if (aValidType || bValidType) {
        return a === b;
      }
      aValidType = isArray$1(a);
      bValidType = isArray$1(b);
      if (aValidType || bValidType) {
        return aValidType && bValidType ? looseCompareNested(a, b, seen, looseCompareArrays) : false;
      }
      aValidType = isObject$1(a);
      bValidType = isObject$1(b);
      if (aValidType || bValidType) {
        if (!aValidType || !bValidType) {
          return false;
        }
        return looseCompareNested(a, b, seen, looseCompareObjects);
      }
      return String(a) === String(b);
    }
    function looseIndexOf(arr, val) {
      return arr.findIndex((item) => looseEqual(item, val));
    }
    const isRef$1 = (val) => {
      return !!(val && val["__v_isRef"] === true);
    };
    const toDisplayString = (val) => {
      return isString(val) ? val : val == null ? "" : isArray$1(val) || isObject$1(val) && (val.toString === objectToString$1 || !isFunction$1(val.toString)) ? isRef$1(val) ? toDisplayString(val.value) : JSON.stringify(val, replacer, 2) : String(val);
    };
    const replacer = (_key, val) => {
      if (isRef$1(val)) {
        return replacer(_key, val.value);
      } else if (isMap(val)) {
        return {
          [`Map(${val.size})`]: [...val.entries()].reduce(
            (entries, [key, val2], i) => {
              entries[stringifySymbol(key, i) + " =>"] = val2;
              return entries;
            },
            {}
          )
        };
      } else if (isSet(val)) {
        return {
          [`Set(${val.size})`]: [...val.values()].map((v) => stringifySymbol(v))
        };
      } else if (isSymbol(val)) {
        return stringifySymbol(val);
      } else if (isObject$1(val) && !isArray$1(val) && !isPlainObject$1(val)) {
        return String(val);
      }
      return val;
    };
    const stringifySymbol = (v, i = "") => {
      var _a;
      return (
        // Symbol.description in es2019+ so we need to cast here to pass
        // the lib: es2016 check
        isSymbol(v) ? `Symbol(${(_a = v.description) != null ? _a : i})` : v
      );
    };
    /**
    * @vue/reactivity v3.5.43
    * (c) 2018-present Yuxi (Evan) You and Vue contributors
    * @license MIT
    **/
    let activeEffectScope;
    class EffectScope {
      // TODO isolatedDeclarations "__v_skip"
      constructor(detached = false) {
        this.detached = detached;
        this._active = true;
        this._on = 0;
        this.effects = [];
        this.cleanups = [];
        this._isPaused = false;
        this._warnOnRun = true;
        this.__v_skip = true;
        if (!detached && activeEffectScope) {
          if (activeEffectScope.active) {
            this.parent = activeEffectScope;
            this.index = (activeEffectScope.scopes || (activeEffectScope.scopes = [])).push(
              this
            ) - 1;
          } else {
            this._active = false;
            this._warnOnRun = false;
          }
        }
      }
      get active() {
        return this._active;
      }
      pause() {
        if (this._active) {
          this._isPaused = true;
          let i, l;
          if (this.scopes) {
            const scopes = this.scopes.slice();
            for (i = 0, l = scopes.length; i < l; i++) {
              scopes[i].pause();
            }
          }
          for (i = 0, l = this.effects.length; i < l; i++) {
            this.effects[i].pause();
          }
        }
      }
      /**
       * Resumes the effect scope, including all child scopes and effects.
       */
      resume() {
        if (this._active) {
          if (this._isPaused) {
            this._isPaused = false;
            let i, l;
            if (this.scopes) {
              const scopes = this.scopes.slice();
              for (i = 0, l = scopes.length; i < l; i++) {
                scopes[i].resume();
              }
            }
            const effects = this.effects.slice();
            for (i = 0, l = effects.length; i < l; i++) {
              effects[i].resume();
            }
          }
        }
      }
      run(fn) {
        if (this._active) {
          const currentEffectScope = activeEffectScope;
          try {
            activeEffectScope = this;
            return fn();
          } finally {
            activeEffectScope = currentEffectScope;
          }
        }
      }
      /**
       * This should only be called on non-detached scopes
       * @internal
       */
      on() {
        if (++this._on === 1) {
          this.prevScope = activeEffectScope;
          activeEffectScope = this;
        }
      }
      /**
       * This should only be called on non-detached scopes
       * @internal
       */
      off() {
        if (this._on > 0 && --this._on === 0) {
          if (activeEffectScope === this) {
            activeEffectScope = this.prevScope;
          } else {
            let current = activeEffectScope;
            while (current) {
              if (current.prevScope === this) {
                current.prevScope = this.prevScope;
                break;
              }
              current = current.prevScope;
            }
          }
          this.prevScope = void 0;
        }
      }
      stop(fromParent) {
        if (this._active) {
          this._active = false;
          let i, l;
          for (i = 0, l = this.effects.length; i < l; i++) {
            this.effects[i].stop();
          }
          this.effects.length = 0;
          for (i = 0, l = this.cleanups.length; i < l; i++) {
            this.cleanups[i]();
          }
          this.cleanups.length = 0;
          if (this.scopes) {
            const scopes = this.scopes.slice();
            for (i = 0, l = scopes.length; i < l; i++) {
              scopes[i].stop(true);
            }
            this.scopes.length = 0;
          }
          if (!this.detached && this.parent && !fromParent) {
            const last = this.parent.scopes.pop();
            if (last && last !== this) {
              this.parent.scopes[this.index] = last;
              last.index = this.index;
            }
          }
          this.parent = void 0;
        }
      }
    }
    function getCurrentScope() {
      return activeEffectScope;
    }
    let activeSub;
    const pausedQueueEffects = /* @__PURE__ */ new WeakSet();
    class ReactiveEffect {
      constructor(fn) {
        this.fn = fn;
        this.deps = void 0;
        this.depsTail = void 0;
        this.flags = 1 | 4;
        this.next = void 0;
        this.cleanup = void 0;
        this.scheduler = void 0;
        if (activeEffectScope) {
          if (activeEffectScope.active) {
            activeEffectScope.effects.push(this);
          } else {
            this.flags &= -2;
          }
        }
      }
      pause() {
        this.flags |= 64;
      }
      resume() {
        if (this.flags & 64) {
          this.flags &= -65;
          if (pausedQueueEffects.has(this)) {
            pausedQueueEffects.delete(this);
            this.trigger();
          }
        }
      }
      /**
       * @internal
       */
      notify() {
        if (this.flags & 2 && !(this.flags & 32)) {
          return;
        }
        if (!(this.flags & 8)) {
          batch(this);
        }
      }
      run() {
        if (!(this.flags & 1)) {
          return this.fn();
        }
        this.flags |= 2;
        cleanupEffect(this);
        prepareDeps(this);
        const prevEffect = activeSub;
        const prevShouldTrack = shouldTrack;
        activeSub = this;
        shouldTrack = true;
        try {
          return this.fn();
        } finally {
          cleanupDeps(this);
          activeSub = prevEffect;
          shouldTrack = prevShouldTrack;
          this.flags &= -3;
        }
      }
      stop() {
        if (this.flags & 1) {
          for (let link = this.deps; link; link = link.nextDep) {
            removeSub(link);
          }
          this.deps = this.depsTail = void 0;
          cleanupEffect(this);
          this.onStop && this.onStop();
          this.flags &= -2;
        }
      }
      trigger() {
        if (this.flags & 64) {
          pausedQueueEffects.add(this);
        } else if (this.scheduler) {
          this.scheduler();
        } else {
          this.runIfDirty();
        }
      }
      /**
       * @internal
       */
      runIfDirty() {
        if (isDirty(this)) {
          this.run();
        }
      }
      get dirty() {
        return isDirty(this);
      }
    }
    let batchDepth = 0;
    let batchedSub;
    let batchedComputed;
    function batch(sub, isComputed = false) {
      sub.flags |= 8;
      if (isComputed) {
        sub.next = batchedComputed;
        batchedComputed = sub;
        return;
      }
      sub.next = batchedSub;
      batchedSub = sub;
    }
    function startBatch() {
      batchDepth++;
    }
    function endBatch() {
      if (--batchDepth > 0) {
        return;
      }
      if (batchedComputed) {
        let e = batchedComputed;
        batchedComputed = void 0;
        while (e) {
          const next = e.next;
          e.next = void 0;
          e.flags &= -9;
          e = next;
        }
      }
      let error;
      while (batchedSub) {
        let e = batchedSub;
        batchedSub = void 0;
        while (e) {
          const next = e.next;
          e.next = void 0;
          e.flags &= -9;
          if (e.flags & 1) {
            try {
              ;
              e.trigger();
            } catch (err) {
              if (!error) error = err;
            }
          }
          e = next;
        }
      }
      if (error) throw error;
    }
    function prepareDeps(sub) {
      for (let link = sub.deps; link; link = link.nextDep) {
        link.version = -1;
        link.prevActiveLink = link.dep.activeLink;
        link.dep.activeLink = link;
      }
    }
    function cleanupDeps(sub) {
      let head;
      let tail = sub.depsTail;
      let link = tail;
      while (link) {
        const prev = link.prevDep;
        if (link.version === -1) {
          if (link === tail) tail = prev;
          removeSub(link);
          removeDep(link);
        } else {
          head = link;
        }
        link.dep.activeLink = link.prevActiveLink;
        link.prevActiveLink = void 0;
        link = prev;
      }
      sub.deps = head;
      sub.depsTail = tail;
    }
    function isDirty(sub) {
      for (let link = sub.deps; link; link = link.nextDep) {
        if (link.dep.version !== link.version || link.dep.computed && (refreshComputed(link.dep.computed) || link.dep.version !== link.version)) {
          return true;
        }
      }
      if (sub._dirty) {
        return true;
      }
      return false;
    }
    function refreshComputed(computed2) {
      if (computed2.flags & 4 && !(computed2.flags & 16)) {
        return;
      }
      computed2.flags &= -17;
      if (computed2.globalVersion === globalVersion) {
        return;
      }
      computed2.globalVersion = globalVersion;
      if (!computed2.isSSR && computed2.flags & 128 && (!computed2.deps && !computed2._dirty || !isDirty(computed2))) {
        return;
      }
      computed2.flags |= 2;
      const dep = computed2.dep;
      const prevSub = activeSub;
      const prevShouldTrack = shouldTrack;
      activeSub = computed2;
      shouldTrack = true;
      try {
        prepareDeps(computed2);
        const value = computed2.fn(computed2._value);
        if (dep.version === 0 || hasChanged(value, computed2._value)) {
          computed2.flags |= 128;
          computed2._value = value;
          dep.version++;
        }
      } catch (err) {
        dep.version++;
        throw err;
      } finally {
        activeSub = prevSub;
        shouldTrack = prevShouldTrack;
        cleanupDeps(computed2);
        computed2.flags &= -3;
      }
    }
    function removeSub(link, soft = false) {
      const { dep, prevSub, nextSub } = link;
      if (prevSub) {
        prevSub.nextSub = nextSub;
        link.prevSub = void 0;
      }
      if (nextSub) {
        nextSub.prevSub = prevSub;
        link.nextSub = void 0;
      }
      if (dep.subs === link) {
        dep.subs = prevSub;
        if (!prevSub && dep.computed) {
          dep.computed.flags &= -5;
          for (let l = dep.computed.deps; l; l = l.nextDep) {
            removeSub(l, true);
          }
        }
      }
      if (!soft && !--dep.sc && dep.map) {
        dep.map.delete(dep.key);
      }
    }
    function removeDep(link) {
      const { prevDep, nextDep } = link;
      if (prevDep) {
        prevDep.nextDep = nextDep;
        link.prevDep = void 0;
      }
      if (nextDep) {
        nextDep.prevDep = prevDep;
        link.nextDep = void 0;
      }
    }
    let shouldTrack = true;
    const trackStack = [];
    function pauseTracking() {
      trackStack.push(shouldTrack);
      shouldTrack = false;
    }
    function resetTracking() {
      const last = trackStack.pop();
      shouldTrack = last === void 0 ? true : last;
    }
    function cleanupEffect(e) {
      const { cleanup } = e;
      e.cleanup = void 0;
      if (cleanup) {
        const prevSub = activeSub;
        activeSub = void 0;
        try {
          cleanup();
        } finally {
          activeSub = prevSub;
        }
      }
    }
    let globalVersion = 0;
    class Link {
      constructor(sub, dep) {
        this.sub = sub;
        this.dep = dep;
        this.version = dep.version;
        this.nextDep = this.prevDep = this.nextSub = this.prevSub = this.prevActiveLink = void 0;
      }
    }
    class Dep {
      // TODO isolatedDeclarations "__v_skip"
      constructor(computed2) {
        this.computed = computed2;
        this.version = 0;
        this.activeLink = void 0;
        this.subs = void 0;
        this.map = void 0;
        this.key = void 0;
        this.sc = 0;
        this.__v_skip = true;
      }
      track(debugInfo) {
        if (!activeSub || !shouldTrack || activeSub === this.computed) {
          return;
        }
        let link = this.activeLink;
        if (link === void 0 || link.sub !== activeSub) {
          link = this.activeLink = new Link(activeSub, this);
          if (!activeSub.deps) {
            activeSub.deps = activeSub.depsTail = link;
          } else {
            link.prevDep = activeSub.depsTail;
            activeSub.depsTail.nextDep = link;
            activeSub.depsTail = link;
          }
          addSub(link);
        } else if (link.version === -1) {
          link.version = this.version;
          if (link.nextDep) {
            const next = link.nextDep;
            next.prevDep = link.prevDep;
            if (link.prevDep) {
              link.prevDep.nextDep = next;
            }
            link.prevDep = activeSub.depsTail;
            link.nextDep = void 0;
            activeSub.depsTail.nextDep = link;
            activeSub.depsTail = link;
            if (activeSub.deps === link) {
              activeSub.deps = next;
            }
          }
        }
        return link;
      }
      trigger(debugInfo) {
        this.version++;
        globalVersion++;
        this.notify(debugInfo);
      }
      notify(debugInfo) {
        startBatch();
        try {
          if (false) ;
          for (let link = this.subs; link; link = link.prevSub) {
            if (link.sub.notify()) {
              ;
              link.sub.dep.notify();
            }
          }
        } finally {
          endBatch();
        }
      }
    }
    function addSub(link) {
      link.dep.sc++;
      if (link.sub.flags & 4) {
        const computed2 = link.dep.computed;
        if (computed2 && !link.dep.subs) {
          computed2.flags |= 4 | 16;
          for (let l = computed2.deps; l; l = l.nextDep) {
            addSub(l);
          }
        }
        const currentTail = link.dep.subs;
        if (currentTail !== link) {
          link.prevSub = currentTail;
          if (currentTail) currentTail.nextSub = link;
        }
        link.dep.subs = link;
      }
    }
    const targetMap = /* @__PURE__ */ new WeakMap();
    const ITERATE_KEY = /* @__PURE__ */ Symbol(
      ""
    );
    const MAP_KEY_ITERATE_KEY = /* @__PURE__ */ Symbol(
      ""
    );
    const ARRAY_ITERATE_KEY = /* @__PURE__ */ Symbol(
      ""
    );
    function track(target, type, key) {
      if (shouldTrack && activeSub) {
        let depsMap = targetMap.get(target);
        if (!depsMap) {
          targetMap.set(target, depsMap = /* @__PURE__ */ new Map());
        }
        let dep = depsMap.get(key);
        if (!dep) {
          depsMap.set(key, dep = new Dep());
          dep.map = depsMap;
          dep.key = key;
        }
        {
          dep.track();
        }
      }
    }
    function trigger(target, type, key, newValue, oldValue, oldTarget) {
      const depsMap = targetMap.get(target);
      if (!depsMap) {
        globalVersion++;
        return;
      }
      const run = (dep) => {
        if (dep) {
          {
            dep.trigger();
          }
        }
      };
      startBatch();
      if (type === "clear") {
        depsMap.forEach(run);
      } else {
        const targetIsArray = isArray$1(target);
        const isArrayIndex = targetIsArray && isIntegerKey(key);
        if (targetIsArray && key === "length") {
          const newLength = Number(newValue);
          depsMap.forEach((dep, key2) => {
            if (key2 === "length" || key2 === ARRAY_ITERATE_KEY || !isSymbol(key2) && key2 >= newLength) {
              run(dep);
            }
          });
        } else {
          if (key !== void 0 || depsMap.has(void 0)) {
            run(depsMap.get(key));
          }
          if (isArrayIndex) {
            run(depsMap.get(ARRAY_ITERATE_KEY));
          }
          switch (type) {
            case "add":
              if (!targetIsArray) {
                run(depsMap.get(ITERATE_KEY));
                if (isMap(target)) {
                  run(depsMap.get(MAP_KEY_ITERATE_KEY));
                }
              } else if (isArrayIndex) {
                run(depsMap.get("length"));
              }
              break;
            case "delete":
              if (!targetIsArray) {
                run(depsMap.get(ITERATE_KEY));
                if (isMap(target)) {
                  run(depsMap.get(MAP_KEY_ITERATE_KEY));
                }
              }
              break;
            case "set":
              if (isMap(target)) {
                run(depsMap.get(ITERATE_KEY));
              }
              break;
          }
        }
      }
      endBatch();
    }
    function getDepFromReactive(object, key) {
      const depMap = targetMap.get(object);
      return depMap && depMap.get(key);
    }
    function reactiveReadArray(array) {
      const raw = /* @__PURE__ */ toRaw(array);
      if (raw === array) return raw;
      track(raw, "iterate", ARRAY_ITERATE_KEY);
      if (/* @__PURE__ */ isShallow(array)) return raw;
      if (!/* @__PURE__ */ isReadonly(array)) return raw.map(toReactive);
      return /* @__PURE__ */ isReactive(array) ? raw.map((item) => toReadonly(toReactive(item))) : raw.map(toReadonly);
    }
    function shallowReadArray(arr) {
      track(arr = /* @__PURE__ */ toRaw(arr), "iterate", ARRAY_ITERATE_KEY);
      return arr;
    }
    function toWrapped(target, item) {
      if (/* @__PURE__ */ isReadonly(target)) {
        return /* @__PURE__ */ isReactive(target) ? toReadonly(toReactive(item)) : toReadonly(item);
      }
      return toReactive(item);
    }
    const arrayInstrumentations = {
      __proto__: null,
      [Symbol.iterator]() {
        return iterator(this, Symbol.iterator, (item) => toWrapped(this, item));
      },
      concat(...args) {
        return reactiveReadArray(this).concat(
          ...args.map((x) => isArray$1(x) ? reactiveReadArray(x) : x)
        );
      },
      entries() {
        return iterator(this, "entries", (value) => {
          value[1] = toWrapped(this, value[1]);
          return value;
        });
      },
      every(fn, thisArg) {
        return apply$1(this, "every", fn, thisArg, void 0, arguments);
      },
      filter(fn, thisArg) {
        return apply$1(
          this,
          "filter",
          fn,
          thisArg,
          (v) => v.map((item) => toWrapped(this, item)),
          arguments
        );
      },
      find(fn, thisArg) {
        return apply$1(
          this,
          "find",
          fn,
          thisArg,
          (item) => toWrapped(this, item),
          arguments
        );
      },
      findIndex(fn, thisArg) {
        return apply$1(this, "findIndex", fn, thisArg, void 0, arguments);
      },
      findLast(fn, thisArg) {
        return apply$1(
          this,
          "findLast",
          fn,
          thisArg,
          (item) => toWrapped(this, item),
          arguments
        );
      },
      findLastIndex(fn, thisArg) {
        return apply$1(this, "findLastIndex", fn, thisArg, void 0, arguments);
      },
      // flat, flatMap could benefit from ARRAY_ITERATE but are not straight-forward to implement
      forEach(fn, thisArg) {
        return apply$1(this, "forEach", fn, thisArg, void 0, arguments);
      },
      includes(...args) {
        return searchProxy(this, "includes", args);
      },
      indexOf(...args) {
        return searchProxy(this, "indexOf", args);
      },
      join(separator) {
        return reactiveReadArray(this).join(separator);
      },
      // keys() iterator only reads `length`, no optimization required
      lastIndexOf(...args) {
        return searchProxy(this, "lastIndexOf", args);
      },
      map(fn, thisArg) {
        return apply$1(this, "map", fn, thisArg, void 0, arguments);
      },
      pop() {
        return noTracking(this, "pop");
      },
      push(...args) {
        return noTracking(this, "push", args);
      },
      reduce(fn, ...args) {
        return reduce(this, "reduce", fn, args);
      },
      reduceRight(fn, ...args) {
        return reduce(this, "reduceRight", fn, args);
      },
      shift() {
        return noTracking(this, "shift");
      },
      // slice could use ARRAY_ITERATE but also seems to beg for range tracking
      some(fn, thisArg) {
        return apply$1(this, "some", fn, thisArg, void 0, arguments);
      },
      splice(...args) {
        return noTracking(this, "splice", args);
      },
      toReversed() {
        return reactiveReadArray(this).toReversed();
      },
      toSorted(comparer) {
        return reactiveReadArray(this).toSorted(comparer);
      },
      toSpliced(...args) {
        return reactiveReadArray(this).toSpliced(...args);
      },
      unshift(...args) {
        return noTracking(this, "unshift", args);
      },
      values() {
        return iterator(this, "values", (item) => toWrapped(this, item));
      }
    };
    function iterator(self2, method, wrapValue) {
      const arr = shallowReadArray(self2);
      const iter = arr[method]();
      if (arr !== self2 && !/* @__PURE__ */ isShallow(self2)) {
        iter._next = iter.next;
        iter.next = () => {
          const result = iter._next();
          if (!result.done) {
            result.value = wrapValue(result.value);
          }
          return result;
        };
      }
      return iter;
    }
    const arrayProto$1 = Array.prototype;
    function apply$1(self2, method, fn, thisArg, wrappedRetFn, args) {
      const arr = shallowReadArray(self2);
      const needsWrap = arr !== self2 && !/* @__PURE__ */ isShallow(self2);
      const methodFn = arr[method];
      if (methodFn !== arrayProto$1[method]) {
        const result2 = methodFn.apply(self2, args);
        return needsWrap ? toReactive(result2) : result2;
      }
      let wrappedFn = fn;
      if (arr !== self2) {
        if (needsWrap) {
          wrappedFn = function(item, index) {
            return fn.call(this, toWrapped(self2, item), index, self2);
          };
        } else if (fn.length > 2) {
          wrappedFn = function(item, index) {
            return fn.call(this, item, index, self2);
          };
        }
      }
      const result = methodFn.call(arr, wrappedFn, thisArg);
      return needsWrap && wrappedRetFn ? wrappedRetFn(result) : result;
    }
    function reduce(self2, method, fn, args) {
      const arr = shallowReadArray(self2);
      const needsWrap = arr !== self2 && !/* @__PURE__ */ isShallow(self2);
      let wrappedFn = fn;
      let wrapInitialAccumulator = false;
      if (arr !== self2) {
        if (needsWrap) {
          wrapInitialAccumulator = args.length === 0;
          wrappedFn = function(acc, item, index) {
            if (wrapInitialAccumulator) {
              wrapInitialAccumulator = false;
              acc = toWrapped(self2, acc);
            }
            return fn.call(this, acc, toWrapped(self2, item), index, self2);
          };
        } else if (fn.length > 3) {
          wrappedFn = function(acc, item, index) {
            return fn.call(this, acc, item, index, self2);
          };
        }
      }
      const result = arr[method](wrappedFn, ...args);
      return wrapInitialAccumulator ? toWrapped(self2, result) : result;
    }
    function searchProxy(self2, method, args) {
      const arr = /* @__PURE__ */ toRaw(self2);
      track(arr, "iterate", ARRAY_ITERATE_KEY);
      const res = arr[method](...args);
      if ((res === -1 || res === false) && /* @__PURE__ */ isProxy(args[0])) {
        args[0] = /* @__PURE__ */ toRaw(args[0]);
        return arr[method](...args);
      }
      return res;
    }
    function noTracking(self2, method, args = []) {
      pauseTracking();
      startBatch();
      const res = (/* @__PURE__ */ toRaw(self2))[method].apply(self2, args);
      endBatch();
      resetTracking();
      return res;
    }
    const isNonTrackableKeys = /* @__PURE__ */ makeMap(`__proto__,__v_isRef,__isVue`);
    const builtInSymbols = new Set(
      /* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((key) => key !== "arguments" && key !== "caller").map((key) => Symbol[key]).filter(isSymbol)
    );
    function hasOwnProperty$8(key) {
      if (!isSymbol(key)) key = String(key);
      const obj = /* @__PURE__ */ toRaw(this);
      track(obj, "has", key);
      return obj.hasOwnProperty(key);
    }
    class BaseReactiveHandler {
      constructor(_isReadonly = false, _isShallow = false) {
        this._isReadonly = _isReadonly;
        this._isShallow = _isShallow;
      }
      get(target, key, receiver) {
        if (key === "__v_skip") return target["__v_skip"];
        const isReadonly2 = this._isReadonly, isShallow2 = this._isShallow;
        if (key === "__v_isReactive") {
          return !isReadonly2;
        } else if (key === "__v_isReadonly") {
          return isReadonly2;
        } else if (key === "__v_isShallow") {
          return isShallow2;
        } else if (key === "__v_raw") {
          if (receiver === (isReadonly2 ? isShallow2 ? shallowReadonlyMap : readonlyMap : isShallow2 ? shallowReactiveMap : reactiveMap).get(target) || // receiver is not the reactive proxy, but has the same prototype
          // this means the receiver is a user proxy of the reactive proxy
          Object.getPrototypeOf(target) === Object.getPrototypeOf(receiver)) {
            return target;
          }
          return;
        }
        const targetIsArray = isArray$1(target);
        if (!isReadonly2) {
          let fn;
          if (targetIsArray && (fn = arrayInstrumentations[key])) {
            return fn;
          }
          if (key === "hasOwnProperty") {
            return hasOwnProperty$8;
          }
        }
        const res = Reflect.get(
          target,
          key,
          // if this is a proxy wrapping a ref, return methods using the raw ref
          // as receiver so that we don't have to call `toRaw` on the ref in all
          // its class methods
          /* @__PURE__ */ isRef(target) ? target : receiver
        );
        if (isSymbol(key) ? builtInSymbols.has(key) : isNonTrackableKeys(key)) {
          return res;
        }
        if (!isReadonly2) {
          track(target, "get", key);
        }
        if (isShallow2) {
          return res;
        }
        if (/* @__PURE__ */ isRef(res)) {
          const value = targetIsArray && isIntegerKey(key) ? res : res.value;
          return isReadonly2 && isObject$1(value) ? /* @__PURE__ */ readonly(value) : value;
        }
        if (isObject$1(res)) {
          return isReadonly2 ? /* @__PURE__ */ readonly(res) : /* @__PURE__ */ reactive(res);
        }
        return res;
      }
    }
    class MutableReactiveHandler extends BaseReactiveHandler {
      constructor(isShallow2 = false) {
        super(false, isShallow2);
      }
      set(target, key, value, receiver) {
        let oldValue = target[key];
        const isArrayWithIntegerKey = isArray$1(target) && isIntegerKey(key);
        if (!this._isShallow) {
          const isOldValueReadonly = /* @__PURE__ */ isReadonly(oldValue);
          if (!/* @__PURE__ */ isShallow(value) && !/* @__PURE__ */ isReadonly(value)) {
            oldValue = /* @__PURE__ */ toRaw(oldValue);
            value = /* @__PURE__ */ toRaw(value);
          }
          if (!isArrayWithIntegerKey && /* @__PURE__ */ isRef(oldValue) && !/* @__PURE__ */ isRef(value)) {
            if (isOldValueReadonly) {
              return true;
            } else {
              oldValue.value = value;
              return true;
            }
          }
        }
        const hadKey = isArrayWithIntegerKey ? Number(key) < target.length : hasOwn(target, key);
        const result = Reflect.set(
          target,
          key,
          value,
          /* @__PURE__ */ isRef(target) ? target : receiver
        );
        if (target === /* @__PURE__ */ toRaw(receiver) && result) {
          if (!hadKey) {
            trigger(target, "add", key, value);
          } else if (hasChanged(value, oldValue)) {
            trigger(target, "set", key, value);
          }
        }
        return result;
      }
      deleteProperty(target, key) {
        const hadKey = hasOwn(target, key);
        target[key];
        const result = Reflect.deleteProperty(target, key);
        if (result && hadKey) {
          trigger(target, "delete", key, void 0);
        }
        return result;
      }
      has(target, key) {
        const result = Reflect.has(target, key);
        if (!isSymbol(key) || !builtInSymbols.has(key)) {
          track(target, "has", key);
        }
        return result;
      }
      ownKeys(target) {
        track(
          target,
          "iterate",
          isArray$1(target) ? "length" : ITERATE_KEY
        );
        return Reflect.ownKeys(target);
      }
    }
    class ReadonlyReactiveHandler extends BaseReactiveHandler {
      constructor(isShallow2 = false) {
        super(true, isShallow2);
      }
      set(target, key) {
        return true;
      }
      deleteProperty(target, key) {
        return true;
      }
    }
    const mutableHandlers = /* @__PURE__ */ new MutableReactiveHandler();
    const readonlyHandlers = /* @__PURE__ */ new ReadonlyReactiveHandler();
    const shallowReactiveHandlers = /* @__PURE__ */ new MutableReactiveHandler(true);
    const shallowReadonlyHandlers = /* @__PURE__ */ new ReadonlyReactiveHandler(true);
    const toShallow = (value) => value;
    const getProto = (v) => Reflect.getPrototypeOf(v);
    function createIterableMethod(method, isReadonly2, isShallow2) {
      return function(...args) {
        const target = this["__v_raw"];
        const rawTarget = /* @__PURE__ */ toRaw(target);
        const targetIsMap = isMap(rawTarget);
        const isPair = method === "entries" || method === Symbol.iterator && targetIsMap;
        const isKeyOnly = method === "keys" && targetIsMap;
        const innerIterator = target[method](...args);
        const wrap = isShallow2 ? toShallow : isReadonly2 ? toReadonly : toReactive;
        !isReadonly2 && track(
          rawTarget,
          "iterate",
          isKeyOnly ? MAP_KEY_ITERATE_KEY : ITERATE_KEY
        );
        return extend(
          // inheriting all iterator properties
          Object.create(innerIterator),
          {
            // iterator protocol
            next() {
              const { value, done } = innerIterator.next();
              return done ? { value, done } : {
                value: isPair ? [wrap(value[0]), wrap(value[1])] : wrap(value),
                done
              };
            }
          }
        );
      };
    }
    function createReadonlyMethod(type) {
      return function(...args) {
        return type === "delete" ? false : type === "clear" ? void 0 : this;
      };
    }
    function createInstrumentations(readonly2, shallow) {
      const instrumentations = {
        get(key) {
          const target = this["__v_raw"];
          const rawTarget = /* @__PURE__ */ toRaw(target);
          const rawKey = /* @__PURE__ */ toRaw(key);
          if (!readonly2) {
            if (hasChanged(key, rawKey)) {
              track(rawTarget, "get", key);
            }
            track(rawTarget, "get", rawKey);
          }
          const { has } = getProto(rawTarget);
          const wrap = shallow ? toShallow : readonly2 ? toReadonly : toReactive;
          if (has.call(rawTarget, key)) {
            return wrap(target.get(key));
          } else if (has.call(rawTarget, rawKey)) {
            return wrap(target.get(rawKey));
          } else if (target !== rawTarget) {
            target.get(key);
          }
        },
        get size() {
          const target = this["__v_raw"];
          !readonly2 && track(/* @__PURE__ */ toRaw(target), "iterate", ITERATE_KEY);
          return target.size;
        },
        has(key) {
          const target = this["__v_raw"];
          const rawTarget = /* @__PURE__ */ toRaw(target);
          const rawKey = /* @__PURE__ */ toRaw(key);
          if (!readonly2) {
            if (hasChanged(key, rawKey)) {
              track(rawTarget, "has", key);
            }
            track(rawTarget, "has", rawKey);
          }
          return key === rawKey ? target.has(key) : target.has(key) || target.has(rawKey);
        },
        forEach(callback, thisArg) {
          const observed = this;
          const target = observed["__v_raw"];
          const rawTarget = /* @__PURE__ */ toRaw(target);
          const wrap = shallow ? toShallow : readonly2 ? toReadonly : toReactive;
          !readonly2 && track(rawTarget, "iterate", ITERATE_KEY);
          return target.forEach((value, key) => {
            return callback.call(thisArg, wrap(value), wrap(key), observed);
          });
        }
      };
      extend(
        instrumentations,
        readonly2 ? {
          add: createReadonlyMethod("add"),
          set: createReadonlyMethod("set"),
          delete: createReadonlyMethod("delete"),
          clear: createReadonlyMethod("clear")
        } : {
          add(value) {
            const target = /* @__PURE__ */ toRaw(this);
            const proto = getProto(target);
            const rawValue = /* @__PURE__ */ toRaw(value);
            const valueToAdd = !shallow && !/* @__PURE__ */ isShallow(value) && !/* @__PURE__ */ isReadonly(value) ? rawValue : value;
            const hadKey = proto.has.call(target, valueToAdd) || hasChanged(value, valueToAdd) && proto.has.call(target, value) || hasChanged(rawValue, valueToAdd) && proto.has.call(target, rawValue);
            if (!hadKey) {
              target.add(valueToAdd);
              trigger(target, "add", valueToAdd, valueToAdd);
            }
            return this;
          },
          set(key, value) {
            if (!shallow && !/* @__PURE__ */ isShallow(value) && !/* @__PURE__ */ isReadonly(value)) {
              value = /* @__PURE__ */ toRaw(value);
            }
            const target = /* @__PURE__ */ toRaw(this);
            const { has, get } = getProto(target);
            let hadKey = has.call(target, key);
            if (!hadKey) {
              key = /* @__PURE__ */ toRaw(key);
              hadKey = has.call(target, key);
            }
            const oldValue = get.call(target, key);
            target.set(key, value);
            if (!hadKey) {
              trigger(target, "add", key, value);
            } else if (hasChanged(value, oldValue)) {
              trigger(target, "set", key, value);
            }
            return this;
          },
          delete(key) {
            const target = /* @__PURE__ */ toRaw(this);
            const { has, get } = getProto(target);
            let hadKey = has.call(target, key);
            if (!hadKey) {
              key = /* @__PURE__ */ toRaw(key);
              hadKey = has.call(target, key);
            }
            get ? get.call(target, key) : void 0;
            const result = target.delete(key);
            if (hadKey) {
              trigger(target, "delete", key, void 0);
            }
            return result;
          },
          clear() {
            const target = /* @__PURE__ */ toRaw(this);
            const hadItems = target.size !== 0;
            const result = target.clear();
            if (hadItems) {
              trigger(
                target,
                "clear",
                void 0,
                void 0
              );
            }
            return result;
          }
        }
      );
      const iteratorMethods = [
        "keys",
        "values",
        "entries",
        Symbol.iterator
      ];
      iteratorMethods.forEach((method) => {
        instrumentations[method] = createIterableMethod(method, readonly2, shallow);
      });
      return instrumentations;
    }
    function createInstrumentationGetter(isReadonly2, shallow) {
      const instrumentations = createInstrumentations(isReadonly2, shallow);
      return (target, key, receiver) => {
        if (key === "__v_isReactive") {
          return !isReadonly2;
        } else if (key === "__v_isReadonly") {
          return isReadonly2;
        } else if (key === "__v_raw") {
          return target;
        }
        return Reflect.get(
          hasOwn(instrumentations, key) && key in target ? instrumentations : target,
          key,
          receiver
        );
      };
    }
    const mutableCollectionHandlers = {
      get: /* @__PURE__ */ createInstrumentationGetter(false, false)
    };
    const shallowCollectionHandlers = {
      get: /* @__PURE__ */ createInstrumentationGetter(false, true)
    };
    const readonlyCollectionHandlers = {
      get: /* @__PURE__ */ createInstrumentationGetter(true, false)
    };
    const shallowReadonlyCollectionHandlers = {
      get: /* @__PURE__ */ createInstrumentationGetter(true, true)
    };
    const reactiveMap = /* @__PURE__ */ new WeakMap();
    const shallowReactiveMap = /* @__PURE__ */ new WeakMap();
    const readonlyMap = /* @__PURE__ */ new WeakMap();
    const shallowReadonlyMap = /* @__PURE__ */ new WeakMap();
    function targetTypeMap(rawType) {
      switch (rawType) {
        case "Object":
        case "Array":
          return 1;
        case "Map":
        case "Set":
        case "WeakMap":
        case "WeakSet":
          return 2;
        default:
          return 0;
      }
    }
    // @__NO_SIDE_EFFECTS__
    function reactive(target) {
      if (/* @__PURE__ */ isReadonly(target)) {
        return target;
      }
      return createReactiveObject(
        target,
        false,
        mutableHandlers,
        mutableCollectionHandlers,
        reactiveMap
      );
    }
    // @__NO_SIDE_EFFECTS__
    function shallowReactive(target) {
      return createReactiveObject(
        target,
        false,
        shallowReactiveHandlers,
        shallowCollectionHandlers,
        shallowReactiveMap
      );
    }
    // @__NO_SIDE_EFFECTS__
    function readonly(target) {
      return createReactiveObject(
        target,
        true,
        readonlyHandlers,
        readonlyCollectionHandlers,
        readonlyMap
      );
    }
    // @__NO_SIDE_EFFECTS__
    function shallowReadonly(target) {
      return createReactiveObject(
        target,
        true,
        shallowReadonlyHandlers,
        shallowReadonlyCollectionHandlers,
        shallowReadonlyMap
      );
    }
    function createReactiveObject(target, isReadonly2, baseHandlers, collectionHandlers, proxyMap) {
      if (!isObject$1(target)) {
        return target;
      }
      if (target["__v_raw"] && !(isReadonly2 && target["__v_isReactive"])) {
        return target;
      }
      if (target["__v_skip"] || !Object.isExtensible(target)) {
        return target;
      }
      const existingProxy = proxyMap.get(target);
      if (existingProxy) {
        return existingProxy;
      }
      const targetType = targetTypeMap(toRawType(target));
      if (targetType === 0) {
        return target;
      }
      const proxy = new Proxy(
        target,
        targetType === 2 ? collectionHandlers : baseHandlers
      );
      proxyMap.set(target, proxy);
      return proxy;
    }
    // @__NO_SIDE_EFFECTS__
    function isReactive(value) {
      if (/* @__PURE__ */ isReadonly(value)) {
        return /* @__PURE__ */ isReactive(value["__v_raw"]);
      }
      return !!(value && value["__v_isReactive"]);
    }
    // @__NO_SIDE_EFFECTS__
    function isReadonly(value) {
      return !!(value && value["__v_isReadonly"]);
    }
    // @__NO_SIDE_EFFECTS__
    function isShallow(value) {
      return !!(value && value["__v_isShallow"]);
    }
    // @__NO_SIDE_EFFECTS__
    function isProxy(value) {
      return value ? !!value["__v_raw"] : false;
    }
    // @__NO_SIDE_EFFECTS__
    function toRaw(observed) {
      const raw = observed && observed["__v_raw"];
      return raw ? /* @__PURE__ */ toRaw(raw) : observed;
    }
    function markRaw(value) {
      if (!hasOwn(value, "__v_skip") && Object.isExtensible(value)) {
        def(value, "__v_skip", true);
      }
      return value;
    }
    const toReactive = (value) => isObject$1(value) ? /* @__PURE__ */ reactive(value) : value;
    const toReadonly = (value) => isObject$1(value) ? /* @__PURE__ */ readonly(value) : value;
    // @__NO_SIDE_EFFECTS__
    function isRef(r) {
      return r ? r["__v_isRef"] === true : false;
    }
    // @__NO_SIDE_EFFECTS__
    function ref(value) {
      return createRef(value, false);
    }
    // @__NO_SIDE_EFFECTS__
    function shallowRef(value) {
      return createRef(value, true);
    }
    function createRef(rawValue, shallow) {
      if (/* @__PURE__ */ isRef(rawValue)) {
        return rawValue;
      }
      return new RefImpl(rawValue, shallow);
    }
    class RefImpl {
      constructor(value, isShallow2) {
        this.dep = new Dep();
        this["__v_isRef"] = true;
        this["__v_isShallow"] = false;
        this._rawValue = isShallow2 ? value : /* @__PURE__ */ toRaw(value);
        this._value = isShallow2 ? value : toReactive(value);
        this["__v_isShallow"] = isShallow2;
      }
      get value() {
        {
          this.dep.track();
        }
        return this._value;
      }
      set value(newValue) {
        const oldValue = this._rawValue;
        const useDirectValue = this["__v_isShallow"] || /* @__PURE__ */ isShallow(newValue) || /* @__PURE__ */ isReadonly(newValue);
        newValue = useDirectValue ? newValue : /* @__PURE__ */ toRaw(newValue);
        if (hasChanged(newValue, oldValue)) {
          this._rawValue = newValue;
          this._value = useDirectValue ? newValue : toReactive(newValue);
          {
            this.dep.trigger();
          }
        }
      }
    }
    function unref(ref2) {
      return /* @__PURE__ */ isRef(ref2) ? ref2.value : ref2;
    }
    const shallowUnwrapHandlers = {
      get: (target, key, receiver) => key === "__v_raw" ? target : unref(Reflect.get(target, key, receiver)),
      set: (target, key, value, receiver) => {
        const oldValue = target[key];
        if (/* @__PURE__ */ isRef(oldValue) && !/* @__PURE__ */ isRef(value)) {
          oldValue.value = value;
          return true;
        } else {
          return Reflect.set(target, key, value, receiver);
        }
      }
    };
    function proxyRefs(objectWithRefs) {
      return /* @__PURE__ */ isReactive(objectWithRefs) ? objectWithRefs : new Proxy(objectWithRefs, shallowUnwrapHandlers);
    }
    class ObjectRefImpl {
      constructor(_object, key, _defaultValue) {
        this._object = _object;
        this._defaultValue = _defaultValue;
        this["__v_isRef"] = true;
        this._value = void 0;
        this._key = isSymbol(key) ? key : String(key);
        this._raw = /* @__PURE__ */ toRaw(_object);
        let shallow = true;
        let obj = _object;
        if (!isArray$1(_object) || isSymbol(this._key) || !isIntegerKey(this._key)) {
          do {
            shallow = !/* @__PURE__ */ isProxy(obj) || /* @__PURE__ */ isShallow(obj);
          } while (shallow && (obj = obj["__v_raw"]));
        }
        this._shallow = shallow;
      }
      get value() {
        let val = this._object[this._key];
        if (this._shallow) {
          val = unref(val);
        }
        return this._value = val === void 0 ? this._defaultValue : val;
      }
      set value(newVal) {
        if (this._shallow && /* @__PURE__ */ isRef(this._raw[this._key])) {
          const nestedRef = this._object[this._key];
          if (/* @__PURE__ */ isRef(nestedRef)) {
            nestedRef.value = newVal;
            return;
          }
        }
        this._object[this._key] = newVal;
      }
      get dep() {
        return getDepFromReactive(this._raw, this._key);
      }
    }
    class GetterRefImpl {
      constructor(_getter) {
        this._getter = _getter;
        this["__v_isRef"] = true;
        this["__v_isReadonly"] = true;
        this._value = void 0;
      }
      get value() {
        return this._value = this._getter();
      }
    }
    // @__NO_SIDE_EFFECTS__
    function toRef(source, key, defaultValue) {
      if (/* @__PURE__ */ isRef(source)) {
        return source;
      } else if (isFunction$1(source)) {
        return new GetterRefImpl(source);
      } else if (isObject$1(source) && arguments.length > 1) {
        return propertyToRef(source, key, defaultValue);
      } else {
        return /* @__PURE__ */ ref(source);
      }
    }
    function propertyToRef(source, key, defaultValue) {
      return new ObjectRefImpl(source, key, defaultValue);
    }
    class ComputedRefImpl {
      constructor(fn, setter, isSSR) {
        this.fn = fn;
        this.setter = setter;
        this._value = void 0;
        this.dep = new Dep(this);
        this.__v_isRef = true;
        this.deps = void 0;
        this.depsTail = void 0;
        this.flags = 16;
        this.globalVersion = globalVersion - 1;
        this.next = void 0;
        this.effect = this;
        this["__v_isReadonly"] = !setter;
        this.isSSR = isSSR;
      }
      /**
       * @internal
       */
      notify() {
        this.flags |= 16;
        if (!(this.flags & 8) && // avoid infinite self recursion
        activeSub !== this) {
          batch(this, true);
          return true;
        }
      }
      get value() {
        const link = this.dep.track();
        refreshComputed(this);
        if (link) {
          link.version = this.dep.version;
        }
        return this._value;
      }
      set value(newValue) {
        if (this.setter) {
          this.setter(newValue);
        }
      }
    }
    // @__NO_SIDE_EFFECTS__
    function computed$1(getterOrOptions, debugOptions, isSSR = false) {
      let getter;
      let setter;
      if (isFunction$1(getterOrOptions)) {
        getter = getterOrOptions;
      } else {
        getter = getterOrOptions.get;
        setter = getterOrOptions.set;
      }
      const cRef = new ComputedRefImpl(getter, setter, isSSR);
      return cRef;
    }
    const INITIAL_WATCHER_VALUE = {};
    const cleanupMap = /* @__PURE__ */ new WeakMap();
    let activeWatcher = void 0;
    function onWatcherCleanup(cleanupFn, failSilently = false, owner = activeWatcher) {
      if (owner) {
        let cleanups = cleanupMap.get(owner);
        if (!cleanups) cleanupMap.set(owner, cleanups = []);
        cleanups.push(cleanupFn);
      }
    }
    function watch$1(source, cb, options = EMPTY_OBJ) {
      const { immediate, deep, once, scheduler, augmentJob, call: call2 } = options;
      const reactiveGetter = (source2) => {
        if (deep) return source2;
        if (/* @__PURE__ */ isShallow(source2) || deep === false || deep === 0)
          return traverse(source2, 1);
        return traverse(source2);
      };
      let effect2;
      let getter;
      let cleanup;
      let boundCleanup;
      let forceTrigger = false;
      let isMultiSource = false;
      if (/* @__PURE__ */ isRef(source)) {
        getter = () => source.value;
        forceTrigger = /* @__PURE__ */ isShallow(source);
      } else if (/* @__PURE__ */ isReactive(source)) {
        getter = () => reactiveGetter(source);
        forceTrigger = true;
      } else if (isArray$1(source)) {
        isMultiSource = true;
        forceTrigger = source.some((s) => /* @__PURE__ */ isReactive(s) || /* @__PURE__ */ isShallow(s));
        getter = () => source.map((s) => {
          if (/* @__PURE__ */ isRef(s)) {
            return s.value;
          } else if (/* @__PURE__ */ isReactive(s)) {
            return reactiveGetter(s);
          } else if (isFunction$1(s)) {
            return call2 ? call2(s, 2) : s();
          } else ;
        });
      } else if (isFunction$1(source)) {
        if (cb) {
          getter = call2 ? () => call2(source, 2) : source;
        } else {
          getter = () => {
            if (cleanup) {
              pauseTracking();
              try {
                cleanup();
              } finally {
                resetTracking();
              }
            }
            const currentEffect = activeWatcher;
            activeWatcher = effect2;
            try {
              return call2 ? call2(source, 3, [boundCleanup]) : source(boundCleanup);
            } finally {
              activeWatcher = currentEffect;
            }
          };
        }
      } else {
        getter = NOOP;
      }
      if (cb && deep) {
        const baseGetter = getter;
        const depth = deep === true ? Infinity : deep;
        getter = () => traverse(baseGetter(), depth);
      }
      const scope = getCurrentScope();
      const watchHandle = () => {
        effect2.stop();
        if (scope && scope.active) {
          remove(scope.effects, effect2);
        }
      };
      if (once && cb) {
        const _cb = cb;
        cb = (...args) => {
          const res = _cb(...args);
          watchHandle();
          return res;
        };
      }
      let oldValue = isMultiSource ? new Array(source.length).fill(INITIAL_WATCHER_VALUE) : INITIAL_WATCHER_VALUE;
      const job = (immediateFirstRun) => {
        if (!(effect2.flags & 1) || !effect2.dirty && !immediateFirstRun) {
          return;
        }
        if (cb) {
          const newValue = effect2.run();
          if (immediateFirstRun || deep || forceTrigger || (isMultiSource ? newValue.some((v, i) => hasChanged(v, oldValue[i])) : hasChanged(newValue, oldValue))) {
            if (cleanup) {
              cleanup();
            }
            const currentWatcher = activeWatcher;
            activeWatcher = effect2;
            try {
              const args = [
                newValue,
                // pass undefined as the old value when it's changed for the first time
                oldValue === INITIAL_WATCHER_VALUE ? void 0 : isMultiSource && oldValue[0] === INITIAL_WATCHER_VALUE ? [] : oldValue,
                boundCleanup
              ];
              oldValue = newValue;
              call2 ? call2(cb, 3, args) : (
                // @ts-expect-error
                cb(...args)
              );
            } finally {
              activeWatcher = currentWatcher;
            }
          }
        } else {
          effect2.run();
        }
      };
      if (augmentJob) {
        augmentJob(job);
      }
      effect2 = new ReactiveEffect(getter);
      effect2.scheduler = scheduler ? () => scheduler(job, false) : job;
      boundCleanup = (fn) => onWatcherCleanup(fn, false, effect2);
      cleanup = effect2.onStop = () => {
        const cleanups = cleanupMap.get(effect2);
        if (cleanups) {
          if (call2) {
            call2(cleanups, 4);
          } else {
            for (const cleanup2 of cleanups) cleanup2();
          }
          cleanupMap.delete(effect2);
        }
      };
      if (cb) {
        if (immediate) {
          job(true);
        } else {
          oldValue = effect2.run();
        }
      } else if (scheduler) {
        scheduler(job.bind(null, true), true);
      } else {
        effect2.run();
      }
      watchHandle.pause = effect2.pause.bind(effect2);
      watchHandle.resume = effect2.resume.bind(effect2);
      watchHandle.stop = watchHandle;
      return watchHandle;
    }
    function traverse(value, depth = Infinity, seen) {
      if (depth <= 0 || !isObject$1(value) || value["__v_skip"]) {
        return value;
      }
      seen = seen || /* @__PURE__ */ new Map();
      if ((seen.get(value) || 0) >= depth) {
        return value;
      }
      seen.set(value, depth);
      depth--;
      if (/* @__PURE__ */ isRef(value)) {
        traverse(value.value, depth, seen);
      } else if (isArray$1(value)) {
        for (let i = 0; i < value.length; i++) {
          traverse(value[i], depth, seen);
        }
      } else if (isSet(value) || isMap(value)) {
        value.forEach((v) => {
          traverse(v, depth, seen);
        });
      } else if (isPlainObject$1(value)) {
        for (const key in value) {
          traverse(value[key], depth, seen);
        }
        for (const key of Object.getOwnPropertySymbols(value)) {
          if (Object.prototype.propertyIsEnumerable.call(value, key)) {
            traverse(value[key], depth, seen);
          }
        }
      }
      return value;
    }
    /**
    * @vue/runtime-core v3.5.43
    * (c) 2018-present Yuxi (Evan) You and Vue contributors
    * @license MIT
    **/
    const stack = [];
    let isWarning = false;
    function warn$1(msg, ...args) {
      if (isWarning) return;
      isWarning = true;
      pauseTracking();
      const instance = stack.length ? stack[stack.length - 1].component : null;
      const appWarnHandler = instance && instance.appContext.config.warnHandler;
      const trace = getComponentTrace();
      if (appWarnHandler) {
        callWithErrorHandling(
          appWarnHandler,
          instance,
          11,
          [
            // eslint-disable-next-line no-restricted-syntax
            msg + args.map((a) => {
              var _a, _b;
              return (_b = (_a = a.toString) == null ? void 0 : _a.call(a)) != null ? _b : JSON.stringify(a);
            }).join(""),
            instance && instance.proxy,
            trace.map(
              ({ vnode }) => `at <${formatComponentName(instance, vnode.type)}>`
            ).join("\n"),
            trace
          ]
        );
      } else {
        const warnArgs = [`[Vue warn]: ${msg}`, ...args];
        if (trace.length && // avoid spamming console during tests
        true) {
          warnArgs.push(`
`, ...formatTrace(trace));
        }
        console.warn(...warnArgs);
      }
      resetTracking();
      isWarning = false;
    }
    function getComponentTrace() {
      let currentVNode = stack[stack.length - 1];
      if (!currentVNode) {
        return [];
      }
      const normalizedStack = [];
      while (currentVNode) {
        const last = normalizedStack[0];
        if (last && last.vnode === currentVNode) {
          last.recurseCount++;
        } else {
          normalizedStack.push({
            vnode: currentVNode,
            recurseCount: 0
          });
        }
        const parentInstance = currentVNode.component && currentVNode.component.parent;
        currentVNode = parentInstance && parentInstance.vnode;
      }
      return normalizedStack;
    }
    function formatTrace(trace) {
      const logs = [];
      trace.forEach((entry, i) => {
        logs.push(...i === 0 ? [] : [`
`], ...formatTraceEntry(entry));
      });
      return logs;
    }
    function formatTraceEntry({ vnode, recurseCount }) {
      const postfix = recurseCount > 0 ? `... (${recurseCount} recursive calls)` : ``;
      const isRoot = vnode.component ? vnode.component.parent == null : false;
      const open = ` at <${formatComponentName(
        vnode.component,
        vnode.type,
        isRoot
      )}`;
      const close = `>` + postfix;
      return vnode.props ? [open, ...formatProps(vnode.props), close] : [open + close];
    }
    function formatProps(props) {
      const res = [];
      const keys = Object.keys(props);
      keys.slice(0, 3).forEach((key) => {
        res.push(...formatProp(key, props[key]));
      });
      if (keys.length > 3) {
        res.push(` ...`);
      }
      return res;
    }
    function formatProp(key, value, raw) {
      if (isString(value)) {
        value = JSON.stringify(value);
        return raw ? value : [`${key}=${value}`];
      } else if (typeof value === "number" || typeof value === "boolean" || value == null) {
        return raw ? value : [`${key}=${value}`];
      } else if (/* @__PURE__ */ isRef(value)) {
        value = formatProp(key, /* @__PURE__ */ toRaw(value.value), true);
        return raw ? value : [`${key}=Ref<`, value, `>`];
      } else if (isFunction$1(value)) {
        return [`${key}=fn${value.name ? `<${value.name}>` : ``}`];
      } else {
        value = /* @__PURE__ */ toRaw(value);
        return raw ? value : [`${key}=`, value];
      }
    }
    function callWithErrorHandling(fn, instance, type, args) {
      try {
        return args ? fn(...args) : fn();
      } catch (err) {
        handleError(err, instance, type);
      }
    }
    function callWithAsyncErrorHandling(fn, instance, type, args) {
      if (isFunction$1(fn)) {
        const res = callWithErrorHandling(fn, instance, type, args);
        if (res && isPromise(res)) {
          res.catch((err) => {
            handleError(err, instance, type);
          });
        }
        return res;
      }
      if (isArray$1(fn)) {
        const values = [];
        for (let i = 0; i < fn.length; i++) {
          values.push(callWithAsyncErrorHandling(fn[i], instance, type, args));
        }
        return values;
      }
    }
    function handleError(err, instance, type, throwInDev = true) {
      const contextVNode = instance ? instance.vnode : null;
      const { errorHandler, throwUnhandledErrorInProduction } = instance && instance.appContext.config || EMPTY_OBJ;
      if (instance) {
        let cur = instance.parent;
        const exposedInstance = instance.proxy;
        const errorInfo = `https://vuejs.org/error-reference/#runtime-${type}`;
        while (cur) {
          const errorCapturedHooks = cur.ec;
          if (errorCapturedHooks) {
            for (let i = 0; i < errorCapturedHooks.length; i++) {
              if (errorCapturedHooks[i](err, exposedInstance, errorInfo) === false) {
                return;
              }
            }
          }
          cur = cur.parent;
        }
        if (errorHandler) {
          pauseTracking();
          callWithErrorHandling(errorHandler, null, 10, [
            err,
            exposedInstance,
            errorInfo
          ]);
          resetTracking();
          return;
        }
      }
      logError(err, type, contextVNode, throwInDev, throwUnhandledErrorInProduction);
    }
    function logError(err, type, contextVNode, throwInDev = true, throwInProd = false) {
      if (throwInProd) {
        throw err;
      } else {
        console.error(err);
      }
    }
    const queue = [];
    let flushIndex = -1;
    const pendingPostFlushCbs = [];
    let activePostFlushCbs = null;
    let postFlushIndex = 0;
    const resolvedPromise = /* @__PURE__ */ Promise.resolve();
    let currentFlushPromise = null;
    function nextTick(fn) {
      const p2 = currentFlushPromise || resolvedPromise;
      return fn ? p2.then(this ? fn.bind(this) : fn) : p2;
    }
    function findInsertionIndex(id) {
      let start = flushIndex + 1;
      let end = queue.length;
      while (start < end) {
        const middle = start + end >>> 1;
        const middleJob = queue[middle];
        const middleJobId = getId(middleJob);
        if (middleJobId < id || middleJobId === id && middleJob.flags & 2) {
          start = middle + 1;
        } else {
          end = middle;
        }
      }
      return start;
    }
    function queueJob(job) {
      if (!(job.flags & 1)) {
        const jobId = getId(job);
        const lastJob = queue[queue.length - 1];
        if (!lastJob || // fast path when the job id is larger than the tail
        !(job.flags & 2) && jobId >= getId(lastJob)) {
          queue.push(job);
        } else {
          queue.splice(findInsertionIndex(jobId), 0, job);
        }
        job.flags |= 1;
        queueFlush();
      }
    }
    function queueFlush() {
      if (!currentFlushPromise) {
        currentFlushPromise = resolvedPromise.then(flushJobs);
      }
    }
    function queuePostFlushCb(cb) {
      if (!isArray$1(cb)) {
        if (activePostFlushCbs && cb.id === -1) {
          activePostFlushCbs.splice(postFlushIndex + 1, 0, cb);
        } else if (!(cb.flags & 1)) {
          pendingPostFlushCbs.push(cb);
          cb.flags |= 1;
        }
      } else {
        for (let i = 0; i < cb.length; i++) {
          pendingPostFlushCbs.push(cb[i]);
        }
      }
      queueFlush();
    }
    function flushPreFlushCbs(instance, seen, i = flushIndex + 1) {
      for (; i < queue.length; i++) {
        const cb = queue[i];
        if (cb && cb.flags & 2) {
          if (instance && cb.id !== instance.uid) {
            continue;
          }
          queue.splice(i, 1);
          i--;
          if (cb.flags & 4) {
            cb.flags &= -2;
          }
          cb();
          if (!(cb.flags & 4)) {
            cb.flags &= -2;
          }
        }
      }
    }
    function flushPostFlushCbs(seen) {
      if (pendingPostFlushCbs.length) {
        const deduped = [...new Set(pendingPostFlushCbs)].sort(
          (a, b) => getId(a) - getId(b)
        );
        pendingPostFlushCbs.length = 0;
        if (activePostFlushCbs) {
          for (let i = 0; i < deduped.length; i++) {
            activePostFlushCbs.push(deduped[i]);
          }
          return;
        }
        activePostFlushCbs = deduped;
        for (postFlushIndex = 0; postFlushIndex < activePostFlushCbs.length; postFlushIndex++) {
          const cb = activePostFlushCbs[postFlushIndex];
          if (cb.flags & 4) {
            cb.flags &= -2;
          }
          if (!(cb.flags & 8)) cb();
          cb.flags &= -2;
        }
        activePostFlushCbs = null;
        postFlushIndex = 0;
      }
    }
    const getId = (job) => job.id == null ? job.flags & 2 ? -1 : Infinity : job.id;
    function flushJobs(seen) {
      try {
        for (flushIndex = 0; flushIndex < queue.length; flushIndex++) {
          const job = queue[flushIndex];
          if (job && !(job.flags & 8)) {
            if (false) ;
            if (job.flags & 4) {
              job.flags &= ~1;
            }
            callWithErrorHandling(
              job,
              job.i,
              job.i ? 15 : 14
            );
            if (!(job.flags & 4)) {
              job.flags &= ~1;
            }
          }
        }
      } finally {
        for (; flushIndex < queue.length; flushIndex++) {
          const job = queue[flushIndex];
          if (job) {
            job.flags &= -2;
          }
        }
        flushIndex = -1;
        queue.length = 0;
        flushPostFlushCbs();
        currentFlushPromise = null;
        if (queue.length || pendingPostFlushCbs.length) {
          flushJobs();
        }
      }
    }
    let currentRenderingInstance = null;
    let currentScopeId = null;
    function setCurrentRenderingInstance(instance) {
      const prev = currentRenderingInstance;
      currentRenderingInstance = instance;
      currentScopeId = instance && instance.type.__scopeId || null;
      return prev;
    }
    function withCtx(fn, ctx = currentRenderingInstance, isNonScopedSlot) {
      if (!ctx) return fn;
      if (fn._n) {
        return fn;
      }
      const renderFnWithContext = (...args) => {
        if (renderFnWithContext._d) {
          setBlockTracking(-1);
        }
        const prevInstance = setCurrentRenderingInstance(ctx);
        const prevStackSize = blockStack.length;
        let res;
        try {
          res = fn(...args);
        } finally {
          for (let i = blockStack.length; i > prevStackSize; i--) closeBlock();
          setCurrentRenderingInstance(prevInstance);
          if (renderFnWithContext._d) {
            setBlockTracking(1);
          }
        }
        return res;
      };
      renderFnWithContext._n = true;
      renderFnWithContext._c = true;
      renderFnWithContext._d = true;
      return renderFnWithContext;
    }
    function withDirectives(vnode, directives) {
      if (currentRenderingInstance === null) {
        return vnode;
      }
      const instance = getComponentPublicInstance(currentRenderingInstance);
      const bindings = vnode.dirs || (vnode.dirs = []);
      for (let i = 0; i < directives.length; i++) {
        let [dir, value, arg, modifiers = EMPTY_OBJ] = directives[i];
        if (dir) {
          if (isFunction$1(dir)) {
            dir = {
              mounted: dir,
              updated: dir
            };
          }
          if (dir.deep) {
            traverse(value);
          }
          bindings.push({
            dir,
            instance,
            value,
            oldValue: void 0,
            arg,
            modifiers
          });
        }
      }
      return vnode;
    }
    function invokeDirectiveHook(vnode, prevVNode, instance, name) {
      const bindings = vnode.dirs;
      const oldBindings = prevVNode && prevVNode.dirs;
      for (let i = 0; i < bindings.length; i++) {
        const binding = bindings[i];
        if (oldBindings) {
          binding.oldValue = oldBindings[i].value;
        }
        let hook = binding.dir[name];
        if (hook) {
          pauseTracking();
          callWithAsyncErrorHandling(hook, instance, 8, [
            vnode.el,
            binding,
            vnode,
            prevVNode
          ]);
          resetTracking();
        }
      }
    }
    function provide(key, value) {
      if (currentInstance) {
        let provides = currentInstance.provides;
        const parentProvides = currentInstance.parent && currentInstance.parent.provides;
        if (parentProvides === provides) {
          provides = currentInstance.provides = Object.create(parentProvides);
        }
        provides[key] = value;
      }
    }
    function inject(key, defaultValue, treatDefaultAsFactory = false) {
      const instance = getCurrentInstance();
      if (instance || currentApp) {
        let provides = currentApp ? currentApp._context.provides : instance ? instance.parent == null || instance.ce ? instance.vnode.appContext && instance.vnode.appContext.provides : instance.parent.provides : void 0;
        if (provides && key in provides) {
          return provides[key];
        } else if (arguments.length > 1) {
          return treatDefaultAsFactory && isFunction$1(defaultValue) ? defaultValue.call(instance && instance.proxy) : defaultValue;
        } else ;
      }
    }
    const ssrContextKey$1 = /* @__PURE__ */ Symbol.for("v-scx");
    const useSSRContext = () => {
      {
        const ctx = inject(ssrContextKey$1);
        return ctx;
      }
    };
    function watchEffect(effect2, options) {
      return doWatch(effect2, null, options);
    }
    function watch(source, cb, options) {
      return doWatch(source, cb, options);
    }
    function doWatch(source, cb, options = EMPTY_OBJ) {
      const { immediate, deep, flush, once } = options;
      const baseWatchOptions = extend({}, options);
      const runsImmediately = cb && immediate || !cb && flush !== "post";
      let ssrCleanup;
      if (isInSSRComponentSetup) {
        if (flush === "sync") {
          const ctx = useSSRContext();
          ssrCleanup = ctx.__watcherHandles || (ctx.__watcherHandles = []);
        } else if (!runsImmediately) {
          const watchStopHandle = () => {
          };
          watchStopHandle.stop = NOOP;
          watchStopHandle.resume = NOOP;
          watchStopHandle.pause = NOOP;
          return watchStopHandle;
        }
      }
      const instance = currentInstance;
      baseWatchOptions.call = (fn, type, args) => callWithAsyncErrorHandling(fn, instance, type, args);
      let isPre = false;
      if (flush === "post") {
        baseWatchOptions.scheduler = (job) => {
          queuePostRenderEffect(job, instance && instance.suspense);
        };
      } else if (flush !== "sync") {
        isPre = true;
        baseWatchOptions.scheduler = (job, isFirstRun) => {
          if (isFirstRun) {
            job();
          } else {
            queueJob(job);
          }
        };
      }
      baseWatchOptions.augmentJob = (job) => {
        if (cb) {
          job.flags |= 4;
        }
        if (isPre) {
          job.flags |= 2;
          if (instance) {
            job.id = instance.uid;
            job.i = instance;
          }
        }
      };
      const watchHandle = watch$1(source, cb, baseWatchOptions);
      if (isInSSRComponentSetup) {
        if (ssrCleanup) {
          ssrCleanup.push(watchHandle);
        } else if (runsImmediately) {
          watchHandle();
        }
      }
      return watchHandle;
    }
    function instanceWatch(source, value, options) {
      const publicThis = this.proxy;
      const getter = isString(source) ? source.includes(".") ? createPathGetter(publicThis, source) : () => publicThis[source] : source.bind(publicThis, publicThis);
      let cb;
      if (isFunction$1(value)) {
        cb = value;
      } else {
        cb = value.handler;
        options = value;
      }
      const reset = setCurrentInstance(this);
      const res = doWatch(getter, cb.bind(publicThis), options);
      reset();
      return res;
    }
    function createPathGetter(ctx, path) {
      const segments = path.split(".");
      return () => {
        let cur = ctx;
        for (let i = 0; i < segments.length && cur; i++) {
          cur = cur[segments[i]];
        }
        return cur;
      };
    }
    const TeleportEndKey = /* @__PURE__ */ Symbol("_vte");
    const isTeleport = (type) => type.__isTeleport;
    const leaveCbKey = /* @__PURE__ */ Symbol("_leaveCb");
    const enterCbKey$1 = /* @__PURE__ */ Symbol("_enterCb");
    function useTransitionState() {
      const state = {
        isMounted: false,
        isLeaving: false,
        isUnmounting: false,
        leavingVNodes: /* @__PURE__ */ new Map()
      };
      onMounted(() => {
        state.isMounted = true;
      });
      onBeforeUnmount(() => {
        state.isUnmounting = true;
      });
      return state;
    }
    const TransitionHookValidator = [Function, Array];
    const BaseTransitionPropsValidators = {
      mode: String,
      appear: Boolean,
      persisted: Boolean,
      // enter
      onBeforeEnter: TransitionHookValidator,
      onEnter: TransitionHookValidator,
      onAfterEnter: TransitionHookValidator,
      onEnterCancelled: TransitionHookValidator,
      // leave
      onBeforeLeave: TransitionHookValidator,
      onLeave: TransitionHookValidator,
      onAfterLeave: TransitionHookValidator,
      onLeaveCancelled: TransitionHookValidator,
      // appear
      onBeforeAppear: TransitionHookValidator,
      onAppear: TransitionHookValidator,
      onAfterAppear: TransitionHookValidator,
      onAppearCancelled: TransitionHookValidator
    };
    const recursiveGetSubtree = (instance) => {
      const subTree = instance.subTree;
      return subTree.component ? recursiveGetSubtree(subTree.component) : subTree;
    };
    const BaseTransitionImpl = {
      name: `BaseTransition`,
      props: BaseTransitionPropsValidators,
      setup(props, { slots }) {
        const instance = getCurrentInstance();
        const state = useTransitionState();
        return () => {
          const children = slots.default && getTransitionRawChildren(slots.default(), true);
          const child = children && children.length ? findNonCommentChild(children) : (
            // Keep explicit default-slot conditionals on the same transition path
            // as regular v-if branches, which render a comment placeholder.
            instance.subTree ? createCommentVNode() : void 0
          );
          if (!child) {
            return;
          }
          const rawProps = /* @__PURE__ */ toRaw(props);
          const { mode } = rawProps;
          if (state.isLeaving) {
            return emptyPlaceholder(child);
          }
          const innerChild = getInnerChild$1(child);
          if (!innerChild) {
            return emptyPlaceholder(child);
          }
          let enterHooks = resolveTransitionHooks(
            innerChild,
            rawProps,
            state,
            instance,
            // #11061, ensure enterHooks is fresh after clone
            (hooks) => enterHooks = hooks
          );
          if (innerChild.type !== Comment) {
            setTransitionHooks(innerChild, enterHooks);
          }
          let oldInnerChild = instance.subTree && getInnerChild$1(instance.subTree);
          if (oldInnerChild && oldInnerChild.type !== Comment && !isSameVNodeType(oldInnerChild, innerChild) && recursiveGetSubtree(instance).type !== Comment) {
            let leavingHooks = resolveTransitionHooks(
              oldInnerChild,
              rawProps,
              state,
              instance
            );
            setTransitionHooks(oldInnerChild, leavingHooks);
            if (mode === "out-in" && innerChild.type !== Comment) {
              state.isLeaving = true;
              leavingHooks.afterLeave = () => {
                state.isLeaving = false;
                if (!(instance.job.flags & 8)) {
                  instance.update();
                }
                delete leavingHooks.afterLeave;
                oldInnerChild = void 0;
              };
              return emptyPlaceholder(child);
            } else if (mode === "in-out" && innerChild.type !== Comment) {
              leavingHooks.delayLeave = (el, earlyRemove, delayedLeave) => {
                const leavingVNodesCache = getLeavingNodesForType(
                  state,
                  oldInnerChild
                );
                leavingVNodesCache[String(oldInnerChild.key)] = oldInnerChild;
                el[leaveCbKey] = () => {
                  earlyRemove();
                  el[leaveCbKey] = void 0;
                  delete enterHooks.delayedLeave;
                  oldInnerChild = void 0;
                };
                enterHooks.delayedLeave = () => {
                  delayedLeave();
                  delete enterHooks.delayedLeave;
                  oldInnerChild = void 0;
                };
              };
            } else {
              oldInnerChild = void 0;
            }
          } else if (oldInnerChild) {
            oldInnerChild = void 0;
          }
          return child;
        };
      }
    };
    function findNonCommentChild(children) {
      let child = children[0];
      if (children.length > 1) {
        for (const c2 of children) {
          if (c2.type !== Comment) {
            child = c2;
            break;
          }
        }
      }
      return child;
    }
    const BaseTransition = BaseTransitionImpl;
    function getLeavingNodesForType(state, vnode) {
      const { leavingVNodes } = state;
      let leavingVNodesCache = leavingVNodes.get(vnode.type);
      if (!leavingVNodesCache) {
        leavingVNodesCache = /* @__PURE__ */ Object.create(null);
        leavingVNodes.set(vnode.type, leavingVNodesCache);
      }
      return leavingVNodesCache;
    }
    function resolveTransitionHooks(vnode, props, state, instance, postClone) {
      const {
        appear,
        mode,
        persisted = false,
        onBeforeEnter,
        onEnter,
        onAfterEnter,
        onEnterCancelled,
        onBeforeLeave,
        onLeave,
        onAfterLeave,
        onLeaveCancelled,
        onBeforeAppear,
        onAppear,
        onAfterAppear,
        onAppearCancelled
      } = props;
      const key = String(vnode.key);
      const leavingVNodesCache = getLeavingNodesForType(state, vnode);
      const callHook2 = (hook, args) => {
        hook && callWithAsyncErrorHandling(
          hook,
          instance,
          9,
          args
        );
      };
      const callAsyncHook = (hook, args) => {
        const done = args[1];
        callHook2(hook, args);
        if (isArray$1(hook)) {
          if (hook.every((hook2) => hook2.length <= 1)) done();
        } else if (hook.length <= 1) {
          done();
        }
      };
      const hooks = {
        mode,
        persisted,
        beforeEnter(el) {
          let hook = onBeforeEnter;
          if (!state.isMounted) {
            if (appear) {
              hook = onBeforeAppear || onBeforeEnter;
            } else {
              return;
            }
          }
          if (el[leaveCbKey]) {
            el[leaveCbKey](
              true
              /* cancelled */
            );
          }
          const leavingVNode = leavingVNodesCache[key];
          if (leavingVNode && isSameVNodeType(vnode, leavingVNode) && leavingVNode.el[leaveCbKey]) {
            leavingVNode.el[leaveCbKey]();
          }
          callHook2(hook, [el]);
        },
        enter(el) {
          if (leavingVNodesCache[key] === vnode) return;
          let hook = onEnter;
          let afterHook = onAfterEnter;
          let cancelHook = onEnterCancelled;
          if (!state.isMounted) {
            if (appear) {
              hook = onAppear || onEnter;
              afterHook = onAfterAppear || onAfterEnter;
              cancelHook = onAppearCancelled || onEnterCancelled;
            } else {
              return;
            }
          }
          let called = false;
          el[enterCbKey$1] = (cancelled) => {
            if (called) return;
            called = true;
            if (cancelled) {
              callHook2(cancelHook, [el]);
            } else {
              callHook2(afterHook, [el]);
            }
            if (hooks.delayedLeave) {
              hooks.delayedLeave();
            }
            el[enterCbKey$1] = void 0;
          };
          const done = el[enterCbKey$1].bind(null, false);
          if (hook) {
            callAsyncHook(hook, [el, done]);
          } else {
            done();
          }
        },
        leave(el, remove2) {
          const key2 = String(vnode.key);
          if (el[enterCbKey$1]) {
            el[enterCbKey$1](
              true
              /* cancelled */
            );
          }
          if (state.isUnmounting) {
            return remove2();
          }
          callHook2(onBeforeLeave, [el]);
          let called = false;
          el[leaveCbKey] = (cancelled) => {
            if (called) return;
            called = true;
            remove2();
            if (cancelled) {
              callHook2(onLeaveCancelled, [el]);
            } else {
              callHook2(onAfterLeave, [el]);
            }
            el[leaveCbKey] = void 0;
            if (leavingVNodesCache[key2] === vnode) {
              delete leavingVNodesCache[key2];
            }
          };
          const done = el[leaveCbKey].bind(null, false);
          leavingVNodesCache[key2] = vnode;
          if (onLeave) {
            callAsyncHook(onLeave, [el, done]);
          } else {
            done();
          }
        },
        clone(vnode2) {
          const hooks2 = resolveTransitionHooks(
            vnode2,
            props,
            state,
            instance,
            postClone
          );
          if (postClone) postClone(hooks2);
          return hooks2;
        }
      };
      return hooks;
    }
    function emptyPlaceholder(vnode) {
      if (isKeepAlive(vnode)) {
        vnode = cloneVNode(vnode);
        vnode.children = null;
        return vnode;
      }
    }
    function getInnerChild$1(vnode) {
      if (!isKeepAlive(vnode)) {
        if (isTeleport(vnode.type) && vnode.children) {
          return findNonCommentChild(vnode.children);
        }
        return vnode;
      }
      if (vnode.component) {
        return vnode.component.subTree;
      }
      const { shapeFlag, children } = vnode;
      if (children) {
        if (shapeFlag & 16) {
          return children[0];
        }
        if (shapeFlag & 32 && isFunction$1(children.default)) {
          return children.default();
        }
      }
    }
    function setTransitionHooks(vnode, hooks) {
      if (vnode.shapeFlag & 6 && vnode.component) {
        vnode.transition = hooks;
        const subTree = vnode.component.subTree;
        setTransitionHooks(
          isTeleport(subTree.type) ? getInnerChild$1(subTree) || subTree : subTree,
          hooks
        );
      } else if (vnode.shapeFlag & 128) {
        vnode.ssContent.transition = hooks.clone(vnode.ssContent);
        vnode.ssFallback.transition = hooks.clone(vnode.ssFallback);
      } else {
        vnode.transition = hooks;
      }
    }
    function getTransitionRawChildren(children, keepComment = false, parentKey) {
      let ret = [];
      let keyedFragmentCount = 0;
      for (let i = 0; i < children.length; i++) {
        let child = children[i];
        const key = parentKey == null ? child.key : String(parentKey) + String(child.key != null ? child.key : i);
        if (child.type === Fragment) {
          if (child.patchFlag & 128) keyedFragmentCount++;
          ret = ret.concat(
            getTransitionRawChildren(child.children, keepComment, key)
          );
        } else if (keepComment || child.type !== Comment) {
          ret.push(key != null ? cloneVNode(child, { key }) : child);
        }
      }
      if (keyedFragmentCount > 1) {
        for (let i = 0; i < ret.length; i++) {
          ret[i].patchFlag = -2;
        }
      }
      return ret;
    }
    // @__NO_SIDE_EFFECTS__
    function defineComponent(options, extraOptions) {
      return isFunction$1(options) ? (
        // #8236: extend call and options.name access are considered side-effects
        // by Rollup, so we have to wrap it in a pure-annotated IIFE.
        /* @__PURE__ */ (() => extend({ name: options.name }, extraOptions, { setup: options }))()
      ) : options;
    }
    function markAsyncBoundary(instance) {
      instance.ids = [instance.ids[0] + instance.ids[2]++ + "-", 0, 0];
    }
    function isTemplateRefKey(refs, key) {
      let desc;
      return !!((desc = Object.getOwnPropertyDescriptor(refs, key)) && !desc.configurable);
    }
    const pendingSetRefMap = /* @__PURE__ */ new WeakMap();
    function setRef(rawRef, oldRawRef, parentSuspense, vnode, isUnmount = false) {
      if (isArray$1(rawRef)) {
        rawRef.forEach(
          (r, i) => setRef(
            r,
            oldRawRef && (isArray$1(oldRawRef) ? oldRawRef[i] : oldRawRef),
            parentSuspense,
            vnode,
            isUnmount
          )
        );
        return;
      }
      if (isAsyncWrapper(vnode) && !isUnmount) {
        if (vnode.shapeFlag & 512 && vnode.type.__asyncResolved && vnode.component.subTree.component) {
          setRef(rawRef, oldRawRef, parentSuspense, vnode.component.subTree);
        }
        return;
      }
      const refValue = vnode.shapeFlag & 4 ? getComponentPublicInstance(vnode.component) : vnode.el;
      const value = isUnmount ? null : refValue;
      const { i: owner, r: ref3 } = rawRef;
      const oldRef = oldRawRef && oldRawRef.r;
      const refs = owner.refs === EMPTY_OBJ ? owner.refs = {} : owner.refs;
      const setupState = owner.setupState;
      const rawSetupState = /* @__PURE__ */ toRaw(setupState);
      const canSetSetupRef = setupState === EMPTY_OBJ ? NO : (key) => {
        if (isTemplateRefKey(refs, key)) {
          return false;
        }
        return hasOwn(rawSetupState, key);
      };
      const canSetRef = (ref22, key) => {
        if (key && isTemplateRefKey(refs, key)) {
          return false;
        }
        return true;
      };
      if (oldRef != null && oldRef !== ref3) {
        invalidatePendingSetRef(oldRawRef);
        if (isString(oldRef)) {
          refs[oldRef] = null;
          if (canSetSetupRef(oldRef)) {
            setupState[oldRef] = null;
          }
        } else if (/* @__PURE__ */ isRef(oldRef)) {
          const oldRawRefAtom = oldRawRef;
          if (canSetRef(oldRef, oldRawRefAtom.k)) {
            oldRef.value = null;
          }
          if (oldRawRefAtom.k) refs[oldRawRefAtom.k] = null;
        }
      }
      if (isFunction$1(ref3)) {
        callWithErrorHandling(ref3, owner, 12, [value, refs]);
      } else {
        const _isString = isString(ref3);
        const _isRef = /* @__PURE__ */ isRef(ref3);
        if (_isString || _isRef) {
          const doSet = () => {
            if (rawRef.f) {
              const existing = _isString ? canSetSetupRef(ref3) ? setupState[ref3] : refs[ref3] : canSetRef() || !rawRef.k ? ref3.value : refs[rawRef.k];
              if (isUnmount) {
                isArray$1(existing) && remove(existing, refValue);
              } else {
                if (!isArray$1(existing)) {
                  if (_isString) {
                    refs[ref3] = [refValue];
                    if (canSetSetupRef(ref3)) {
                      setupState[ref3] = refs[ref3];
                    }
                  } else {
                    const newVal = [refValue];
                    if (canSetRef(ref3, rawRef.k)) {
                      ref3.value = newVal;
                    }
                    if (rawRef.k) refs[rawRef.k] = newVal;
                  }
                } else if (!existing.includes(refValue)) {
                  existing.push(refValue);
                }
              }
            } else if (_isString) {
              refs[ref3] = value;
              if (canSetSetupRef(ref3)) {
                setupState[ref3] = value;
              }
            } else if (_isRef) {
              if (canSetRef(ref3, rawRef.k)) {
                ref3.value = value;
              }
              if (rawRef.k) refs[rawRef.k] = value;
            } else ;
          };
          if (value) {
            const job = () => {
              doSet();
              pendingSetRefMap.delete(rawRef);
            };
            job.id = -1;
            pendingSetRefMap.set(rawRef, job);
            queuePostRenderEffect(job, parentSuspense);
          } else {
            invalidatePendingSetRef(rawRef);
            doSet();
          }
        }
      }
    }
    function invalidatePendingSetRef(rawRef) {
      const pendingSetRef = pendingSetRefMap.get(rawRef);
      if (pendingSetRef) {
        pendingSetRef.flags |= 8;
        pendingSetRefMap.delete(rawRef);
      }
    }
    getGlobalThis().requestIdleCallback || ((cb) => setTimeout(cb, 1));
    getGlobalThis().cancelIdleCallback || ((id) => clearTimeout(id));
    const isAsyncWrapper = (i) => !!i.type.__asyncLoader;
    const isKeepAlive = (vnode) => vnode.type.__isKeepAlive;
    function onActivated(hook, target) {
      registerKeepAliveHook(hook, "a", target);
    }
    function onDeactivated(hook, target) {
      registerKeepAliveHook(hook, "da", target);
    }
    function registerKeepAliveHook(hook, type, target = currentInstance) {
      const wrappedHook = hook.__wdc || (hook.__wdc = () => {
        let current = target;
        while (current) {
          if (current.isDeactivated) {
            return;
          }
          current = current.parent;
        }
        return hook();
      });
      injectHook(type, wrappedHook, target);
      if (target) {
        let current = target.parent;
        while (current && current.parent) {
          if (isKeepAlive(current.parent.vnode)) {
            injectToKeepAliveRoot(wrappedHook, type, target, current);
          }
          current = current.parent;
        }
      }
    }
    function injectToKeepAliveRoot(hook, type, target, keepAliveRoot) {
      const injected = injectHook(
        type,
        hook,
        keepAliveRoot,
        true
        /* prepend */
      );
      onUnmounted(() => {
        remove(keepAliveRoot[type], injected);
      }, target);
    }
    function injectHook(type, hook, target = currentInstance, prepend = false) {
      if (target) {
        const hooks = target[type] || (target[type] = []);
        const wrappedHook = hook.__weh || (hook.__weh = (...args) => {
          pauseTracking();
          const reset = setCurrentInstance(target);
          const res = callWithAsyncErrorHandling(hook, target, type, args);
          reset();
          resetTracking();
          return res;
        });
        if (prepend) {
          hooks.unshift(wrappedHook);
        } else {
          hooks.push(wrappedHook);
        }
        return wrappedHook;
      }
    }
    const createHook = (lifecycle) => (hook, target = currentInstance) => {
      if (!isInSSRComponentSetup || lifecycle === "sp") {
        injectHook(lifecycle, (...args) => hook(...args), target);
      }
    };
    const onBeforeMount = createHook("bm");
    const onMounted = createHook("m");
    const onBeforeUpdate = createHook(
      "bu"
    );
    const onUpdated = createHook("u");
    const onBeforeUnmount = createHook(
      "bum"
    );
    const onUnmounted = createHook("um");
    const onServerPrefetch = createHook(
      "sp"
    );
    const onRenderTriggered = createHook("rtg");
    const onRenderTracked = createHook("rtc");
    function onErrorCaptured(hook, target = currentInstance) {
      injectHook("ec", hook, target);
    }
    const COMPONENTS = "components";
    const NULL_DYNAMIC_COMPONENT = /* @__PURE__ */ Symbol.for("v-ndc");
    function resolveDynamicComponent(component) {
      if (isString(component)) {
        return resolveAsset(COMPONENTS, component, false) || component;
      } else {
        return component || NULL_DYNAMIC_COMPONENT;
      }
    }
    function resolveAsset(type, name, warnMissing = true, maybeSelfReference = false) {
      const instance = currentRenderingInstance || currentInstance;
      if (instance) {
        const Component = instance.type;
        {
          const selfName = getComponentName(
            Component,
            false
          );
          if (selfName && (selfName === name || selfName === camelize(name) || selfName === capitalize(camelize(name)))) {
            return Component;
          }
        }
        const res = (
          // local registration
          // check instance[type] first which is resolved for options API
          resolve(instance[type] || Component[type], name) || // global registration
          resolve(instance.appContext[type], name)
        );
        if (!res && maybeSelfReference) {
          return Component;
        }
        return res;
      }
    }
    function resolve(registry, name) {
      return registry && (registry[name] || registry[camelize(name)] || registry[capitalize(camelize(name))]);
    }
    function renderList(source, renderItem, cache, index) {
      let ret;
      const cached = cache;
      const sourceIsArray = isArray$1(source);
      if (sourceIsArray || isString(source)) {
        const sourceIsReactiveArray = sourceIsArray && /* @__PURE__ */ isReactive(source);
        let needsWrap = false;
        let isReadonlySource = false;
        if (sourceIsReactiveArray) {
          needsWrap = !/* @__PURE__ */ isShallow(source);
          isReadonlySource = /* @__PURE__ */ isReadonly(source);
          source = shallowReadArray(source);
        }
        ret = new Array(source.length);
        for (let i = 0, l = source.length; i < l; i++) {
          ret[i] = renderItem(
            needsWrap ? isReadonlySource ? toReadonly(toReactive(source[i])) : toReactive(source[i]) : source[i],
            i,
            void 0,
            cached
          );
        }
      } else if (typeof source === "number") {
        {
          ret = new Array(source);
          for (let i = 0; i < source; i++) {
            ret[i] = renderItem(i + 1, i, void 0, cached);
          }
        }
      } else if (isObject$1(source)) {
        if (source[Symbol.iterator]) {
          ret = Array.from(
            source,
            (item, i) => renderItem(item, i, void 0, cached)
          );
        } else {
          const keys = Object.keys(source);
          ret = new Array(keys.length);
          for (let i = 0, l = keys.length; i < l; i++) {
            const key = keys[i];
            ret[i] = renderItem(source[key], key, i, cached);
          }
        }
      } else {
        ret = [];
      }
      return ret;
    }
    const getPublicInstance = (i) => {
      if (!i) return null;
      if (isStatefulComponent(i)) return getComponentPublicInstance(i);
      return getPublicInstance(i.parent);
    };
    const publicPropertiesMap = (
      // Move PURE marker to new line to workaround compiler discarding it
      // due to type annotation
      /* @__PURE__ */ extend(/* @__PURE__ */ Object.create(null), {
        $: (i) => i,
        $el: (i) => i.vnode.el,
        $data: (i) => i.data,
        $props: (i) => i.props,
        $attrs: (i) => i.attrs,
        $slots: (i) => i.slots,
        $refs: (i) => i.refs,
        $parent: (i) => getPublicInstance(i.parent),
        $root: (i) => getPublicInstance(i.root),
        $host: (i) => i.ce,
        $emit: (i) => i.emit,
        $options: (i) => resolveMergedOptions(i),
        $forceUpdate: (i) => i.f || (i.f = () => {
          queueJob(i.update);
        }),
        $nextTick: (i) => i.n || (i.n = nextTick.bind(i.proxy)),
        $watch: (i) => instanceWatch.bind(i)
      })
    );
    const hasSetupBinding = (state, key) => state !== EMPTY_OBJ && !state.__isScriptSetup && hasOwn(state, key);
    const PublicInstanceProxyHandlers = {
      get({ _: instance }, key) {
        if (key === "__v_skip") {
          return true;
        }
        const { ctx, setupState, data, props, accessCache, type, appContext } = instance;
        if (key[0] !== "$") {
          const n = accessCache[key];
          if (n !== void 0) {
            switch (n) {
              case 1:
                return setupState[key];
              case 2:
                return data[key];
              case 4:
                return ctx[key];
              case 3:
                return props[key];
            }
          } else if (hasSetupBinding(setupState, key)) {
            accessCache[key] = 1;
            return setupState[key];
          } else if (data !== EMPTY_OBJ && hasOwn(data, key)) {
            accessCache[key] = 2;
            return data[key];
          } else if (hasOwn(props, key)) {
            accessCache[key] = 3;
            return props[key];
          } else if (ctx !== EMPTY_OBJ && hasOwn(ctx, key)) {
            accessCache[key] = 4;
            return ctx[key];
          } else if (shouldCacheAccess) {
            accessCache[key] = 0;
          }
        }
        const publicGetter = publicPropertiesMap[key];
        let cssModule, globalProperties;
        if (publicGetter) {
          if (key === "$attrs") {
            track(instance.attrs, "get", "");
          }
          return publicGetter(instance);
        } else if (
          // css module (injected by vue-loader)
          (cssModule = type.__cssModules) && (cssModule = cssModule[key])
        ) {
          return cssModule;
        } else if (ctx !== EMPTY_OBJ && hasOwn(ctx, key)) {
          accessCache[key] = 4;
          return ctx[key];
        } else if (
          // global properties
          globalProperties = appContext.config.globalProperties, hasOwn(globalProperties, key)
        ) {
          {
            return globalProperties[key];
          }
        } else ;
      },
      set({ _: instance }, key, value) {
        const { data, setupState, ctx } = instance;
        if (hasSetupBinding(setupState, key)) {
          setupState[key] = value;
          return true;
        } else if (data !== EMPTY_OBJ && hasOwn(data, key)) {
          data[key] = value;
          return true;
        } else if (hasOwn(instance.props, key)) {
          return false;
        }
        if (key[0] === "$" && key.slice(1) in instance) {
          return false;
        } else {
          {
            ctx[key] = value;
          }
        }
        return true;
      },
      has({
        _: { data, setupState, accessCache, ctx, appContext, props, type }
      }, key) {
        let cssModules;
        return !!(accessCache[key] || data !== EMPTY_OBJ && key[0] !== "$" && hasOwn(data, key) || hasSetupBinding(setupState, key) || hasOwn(props, key) || hasOwn(ctx, key) || hasOwn(publicPropertiesMap, key) || hasOwn(appContext.config.globalProperties, key) || (cssModules = type.__cssModules) && cssModules[key]);
      },
      defineProperty(target, key, descriptor) {
        if (descriptor.get != null) {
          target._.accessCache[key] = 0;
        } else if (hasOwn(descriptor, "value")) {
          this.set(target, key, descriptor.value, null);
        }
        return Reflect.defineProperty(target, key, descriptor);
      }
    };
    function normalizePropsOrEmits(props) {
      return isArray$1(props) ? props.reduce(
        (normalized, p2) => (normalized[p2] = null, normalized),
        {}
      ) : props;
    }
    let shouldCacheAccess = true;
    function applyOptions(instance) {
      const options = resolveMergedOptions(instance);
      const publicThis = instance.proxy;
      const ctx = instance.ctx;
      shouldCacheAccess = false;
      if (options.beforeCreate) {
        callHook$1(options.beforeCreate, instance, "bc");
      }
      const {
        // state
        data: dataOptions,
        computed: computedOptions,
        methods,
        watch: watchOptions,
        provide: provideOptions,
        inject: injectOptions,
        // lifecycle
        created,
        beforeMount,
        mounted: mounted2,
        beforeUpdate,
        updated,
        activated,
        deactivated,
        beforeDestroy,
        beforeUnmount,
        destroyed,
        unmounted,
        render: render2,
        renderTracked,
        renderTriggered,
        errorCaptured,
        serverPrefetch,
        // public API
        expose,
        inheritAttrs,
        // assets
        components,
        directives,
        filters
      } = options;
      const checkDuplicateProperties = null;
      if (injectOptions) {
        resolveInjections(injectOptions, ctx, checkDuplicateProperties);
      }
      if (methods) {
        for (const key in methods) {
          const methodHandler = methods[key];
          if (isFunction$1(methodHandler)) {
            {
              ctx[key] = methodHandler.bind(publicThis);
            }
          }
        }
      }
      if (dataOptions) {
        const data = dataOptions.call(publicThis, publicThis);
        if (!isObject$1(data)) ;
        else {
          instance.data = /* @__PURE__ */ reactive(data);
        }
      }
      shouldCacheAccess = true;
      if (computedOptions) {
        for (const key in computedOptions) {
          const opt = computedOptions[key];
          const get = isFunction$1(opt) ? opt.bind(publicThis, publicThis) : isFunction$1(opt.get) ? opt.get.bind(publicThis, publicThis) : NOOP;
          const set = !isFunction$1(opt) && isFunction$1(opt.set) ? opt.set.bind(publicThis) : NOOP;
          const c2 = computed({
            get,
            set
          });
          Object.defineProperty(ctx, key, {
            enumerable: true,
            configurable: true,
            get: () => c2.value,
            set: (v) => c2.value = v
          });
        }
      }
      if (watchOptions) {
        for (const key in watchOptions) {
          createWatcher(watchOptions[key], ctx, publicThis, key);
        }
      }
      if (provideOptions) {
        const provides = isFunction$1(provideOptions) ? provideOptions.call(publicThis) : provideOptions;
        Reflect.ownKeys(provides).forEach((key) => {
          provide(key, provides[key]);
        });
      }
      if (created) {
        callHook$1(created, instance, "c");
      }
      function registerLifecycleHook(register, hook) {
        if (isArray$1(hook)) {
          hook.forEach((_hook) => register(_hook.bind(publicThis)));
        } else if (hook) {
          register(hook.bind(publicThis));
        }
      }
      registerLifecycleHook(onBeforeMount, beforeMount);
      registerLifecycleHook(onMounted, mounted2);
      registerLifecycleHook(onBeforeUpdate, beforeUpdate);
      registerLifecycleHook(onUpdated, updated);
      registerLifecycleHook(onActivated, activated);
      registerLifecycleHook(onDeactivated, deactivated);
      registerLifecycleHook(onErrorCaptured, errorCaptured);
      registerLifecycleHook(onRenderTracked, renderTracked);
      registerLifecycleHook(onRenderTriggered, renderTriggered);
      registerLifecycleHook(onBeforeUnmount, beforeUnmount);
      registerLifecycleHook(onUnmounted, unmounted);
      registerLifecycleHook(onServerPrefetch, serverPrefetch);
      if (isArray$1(expose)) {
        if (expose.length) {
          const exposed = instance.exposed || (instance.exposed = {});
          expose.forEach((key) => {
            Object.defineProperty(exposed, key, {
              get: () => publicThis[key],
              set: (val) => publicThis[key] = val,
              enumerable: true
            });
          });
        } else if (!instance.exposed) {
          instance.exposed = {};
        }
      }
      if (render2 && instance.render === NOOP) {
        instance.render = render2;
      }
      if (inheritAttrs != null) {
        instance.inheritAttrs = inheritAttrs;
      }
      if (components) instance.components = components;
      if (directives) instance.directives = directives;
      if (serverPrefetch) {
        markAsyncBoundary(instance);
      }
    }
    function resolveInjections(injectOptions, ctx, checkDuplicateProperties = NOOP) {
      if (isArray$1(injectOptions)) {
        injectOptions = normalizeInject(injectOptions);
      }
      for (const key in injectOptions) {
        const opt = injectOptions[key];
        let injected;
        if (isObject$1(opt)) {
          if ("default" in opt) {
            injected = inject(
              opt.from || key,
              opt.default,
              true
            );
          } else {
            injected = inject(opt.from || key);
          }
        } else {
          injected = inject(opt);
        }
        if (/* @__PURE__ */ isRef(injected)) {
          Object.defineProperty(ctx, key, {
            enumerable: true,
            configurable: true,
            get: () => injected.value,
            set: (v) => injected.value = v
          });
        } else {
          ctx[key] = injected;
        }
      }
    }
    function callHook$1(hook, instance, type) {
      callWithAsyncErrorHandling(
        isArray$1(hook) ? hook.map((h2) => h2.bind(instance.proxy)) : hook.bind(instance.proxy),
        instance,
        type
      );
    }
    function createWatcher(raw, ctx, publicThis, key) {
      let getter = key.includes(".") ? createPathGetter(publicThis, key) : () => publicThis[key];
      if (isString(raw)) {
        const handler = ctx[raw];
        if (isFunction$1(handler)) {
          {
            watch(getter, handler);
          }
        }
      } else if (isFunction$1(raw)) {
        {
          watch(getter, raw.bind(publicThis));
        }
      } else if (isObject$1(raw)) {
        if (isArray$1(raw)) {
          raw.forEach((r) => createWatcher(r, ctx, publicThis, key));
        } else {
          const handler = isFunction$1(raw.handler) ? raw.handler.bind(publicThis) : ctx[raw.handler];
          if (isFunction$1(handler)) {
            watch(getter, handler, raw);
          }
        }
      } else ;
    }
    function resolveMergedOptions(instance) {
      const base2 = instance.type;
      const { mixins, extends: extendsOptions } = base2;
      const {
        mixins: globalMixins,
        optionsCache: cache,
        config: { optionMergeStrategies }
      } = instance.appContext;
      const cached = cache.get(base2);
      let resolved;
      if (cached) {
        resolved = cached;
      } else if (!globalMixins.length && !mixins && !extendsOptions) {
        {
          resolved = base2;
        }
      } else {
        resolved = {};
        if (globalMixins.length) {
          globalMixins.forEach(
            (m) => mergeOptions(resolved, m, optionMergeStrategies, true)
          );
        }
        mergeOptions(resolved, base2, optionMergeStrategies);
      }
      if (isObject$1(base2)) {
        cache.set(base2, resolved);
      }
      return resolved;
    }
    function mergeOptions(to, from, strats, asMixin = false) {
      const { mixins, extends: extendsOptions } = from;
      if (extendsOptions) {
        mergeOptions(to, extendsOptions, strats, true);
      }
      if (mixins) {
        mixins.forEach(
          (m) => mergeOptions(to, m, strats, true)
        );
      }
      for (const key in from) {
        if (asMixin && key === "expose") ;
        else {
          const strat = internalOptionMergeStrats[key] || strats && strats[key];
          to[key] = strat ? strat(to[key], from[key]) : from[key];
        }
      }
      return to;
    }
    const internalOptionMergeStrats = {
      data: mergeDataFn,
      props: mergeEmitsOrPropsOptions,
      emits: mergeEmitsOrPropsOptions,
      // objects
      methods: mergeObjectOptions,
      computed: mergeObjectOptions,
      // lifecycle
      beforeCreate: mergeAsArray,
      created: mergeAsArray,
      beforeMount: mergeAsArray,
      mounted: mergeAsArray,
      beforeUpdate: mergeAsArray,
      updated: mergeAsArray,
      beforeDestroy: mergeAsArray,
      beforeUnmount: mergeAsArray,
      destroyed: mergeAsArray,
      unmounted: mergeAsArray,
      activated: mergeAsArray,
      deactivated: mergeAsArray,
      errorCaptured: mergeAsArray,
      serverPrefetch: mergeAsArray,
      // assets
      components: mergeObjectOptions,
      directives: mergeObjectOptions,
      // watch
      watch: mergeWatchOptions,
      // provide / inject
      provide: mergeDataFn,
      inject: mergeInject
    };
    function mergeDataFn(to, from) {
      if (!from) {
        return to;
      }
      if (!to) {
        return from;
      }
      return function mergedDataFn() {
        return extend(
          isFunction$1(to) ? to.call(this, this) : to,
          isFunction$1(from) ? from.call(this, this) : from
        );
      };
    }
    function mergeInject(to, from) {
      return mergeObjectOptions(normalizeInject(to), normalizeInject(from));
    }
    function normalizeInject(raw) {
      if (isArray$1(raw)) {
        const res = {};
        for (let i = 0; i < raw.length; i++) {
          res[raw[i]] = raw[i];
        }
        return res;
      }
      return raw;
    }
    function mergeAsArray(to, from) {
      return to ? [...new Set([].concat(to, from))] : from;
    }
    function mergeObjectOptions(to, from) {
      return to ? extend(/* @__PURE__ */ Object.create(null), to, from) : from;
    }
    function mergeEmitsOrPropsOptions(to, from) {
      if (to) {
        if (isArray$1(to) && isArray$1(from)) {
          return [.../* @__PURE__ */ new Set([...to, ...from])];
        }
        return extend(
          /* @__PURE__ */ Object.create(null),
          normalizePropsOrEmits(to),
          normalizePropsOrEmits(from != null ? from : {})
        );
      } else {
        return from;
      }
    }
    function mergeWatchOptions(to, from) {
      if (!to) return from;
      if (!from) return to;
      const merged = extend(/* @__PURE__ */ Object.create(null), to);
      for (const key in from) {
        merged[key] = mergeAsArray(to[key], from[key]);
      }
      return merged;
    }
    function createAppContext() {
      return {
        app: null,
        config: {
          isNativeTag: NO,
          performance: false,
          globalProperties: {},
          optionMergeStrategies: {},
          errorHandler: void 0,
          warnHandler: void 0,
          compilerOptions: {}
        },
        mixins: [],
        components: {},
        directives: {},
        provides: /* @__PURE__ */ Object.create(null),
        optionsCache: /* @__PURE__ */ new WeakMap(),
        propsCache: /* @__PURE__ */ new WeakMap(),
        emitsCache: /* @__PURE__ */ new WeakMap()
      };
    }
    let uid$1 = 0;
    function createAppAPI(render2, hydrate) {
      return function createApp2(rootComponent, rootProps = null) {
        if (!isFunction$1(rootComponent)) {
          rootComponent = extend({}, rootComponent);
        }
        if (rootProps != null && !isObject$1(rootProps)) {
          rootProps = null;
        }
        const context = createAppContext();
        const installedPlugins = /* @__PURE__ */ new WeakSet();
        const pluginCleanupFns = [];
        let isMounted2 = false;
        const app = context.app = {
          _uid: uid$1++,
          _component: rootComponent,
          _props: rootProps,
          _container: null,
          _context: context,
          _instance: null,
          version,
          get config() {
            return context.config;
          },
          set config(v) {
          },
          use(plugin2, ...options) {
            if (installedPlugins.has(plugin2)) ;
            else if (plugin2 && isFunction$1(plugin2.install)) {
              installedPlugins.add(plugin2);
              plugin2.install(app, ...options);
            } else if (isFunction$1(plugin2)) {
              installedPlugins.add(plugin2);
              plugin2(app, ...options);
            } else ;
            return app;
          },
          mixin(mixin) {
            {
              if (!context.mixins.includes(mixin)) {
                context.mixins.push(mixin);
              }
            }
            return app;
          },
          component(name, component) {
            if (!component) {
              return context.components[name];
            }
            context.components[name] = component;
            return app;
          },
          directive(name, directive) {
            if (!directive) {
              return context.directives[name];
            }
            context.directives[name] = directive;
            return app;
          },
          mount(rootContainer, isHydrate, namespace) {
            if (!isMounted2) {
              const vnode = app._ceVNode || createVNode(rootComponent, rootProps);
              vnode.appContext = context;
              if (namespace === true) {
                namespace = "svg";
              } else if (namespace === false) {
                namespace = void 0;
              }
              {
                render2(vnode, rootContainer, namespace);
              }
              isMounted2 = true;
              app._container = rootContainer;
              rootContainer.__vue_app__ = app;
              return getComponentPublicInstance(vnode.component);
            }
          },
          onUnmount(cleanupFn) {
            pluginCleanupFns.push(cleanupFn);
          },
          unmount() {
            if (isMounted2) {
              callWithAsyncErrorHandling(
                pluginCleanupFns,
                app._instance,
                16
              );
              render2(null, app._container);
              delete app._container.__vue_app__;
            }
          },
          provide(key, value) {
            context.provides[key] = value;
            return app;
          },
          runWithContext(fn) {
            const lastApp = currentApp;
            currentApp = app;
            try {
              return fn();
            } finally {
              currentApp = lastApp;
            }
          }
        };
        return app;
      };
    }
    let currentApp = null;
    const getModelModifiers = (props, modelName) => {
      return modelName === "modelValue" || modelName === "model-value" ? props.modelModifiers : props[`${modelName}Modifiers`] || props[`${camelize(modelName)}Modifiers`] || props[`${hyphenate(modelName)}Modifiers`];
    };
    function emit(instance, event, ...rawArgs) {
      if (instance.isUnmounted) return;
      const props = instance.vnode.props || EMPTY_OBJ;
      let args = rawArgs;
      const isModelListener2 = event.startsWith("update:");
      const modifiers = isModelListener2 && getModelModifiers(props, event.slice(7));
      if (modifiers) {
        if (modifiers.trim) {
          args = rawArgs.map((a) => isString(a) ? a.trim() : a);
        }
        if (modifiers.number) {
          args = args.map(looseToNumber);
        }
      }
      let handlerName;
      let handler = props[handlerName = toHandlerKey(event)] || // also try camelCase event handler (#2249)
      props[handlerName = toHandlerKey(camelize(event))];
      if (!handler && isModelListener2) {
        handler = props[handlerName = toHandlerKey(hyphenate(event))];
      }
      if (handler) {
        callWithAsyncErrorHandling(
          handler,
          instance,
          6,
          args
        );
      }
      const onceHandler = props[handlerName + `Once`];
      if (onceHandler) {
        if (!instance.emitted) {
          instance.emitted = {};
        } else if (instance.emitted[handlerName]) {
          return;
        }
        instance.emitted[handlerName] = true;
        callWithAsyncErrorHandling(
          onceHandler,
          instance,
          6,
          args
        );
      }
    }
    const mixinEmitsCache = /* @__PURE__ */ new WeakMap();
    function normalizeEmitsOptions(comp, appContext, asMixin = false) {
      const cache = asMixin ? mixinEmitsCache : appContext.emitsCache;
      const cached = cache.get(comp);
      if (cached !== void 0) {
        return cached;
      }
      const raw = comp.emits;
      let normalized = {};
      let hasExtends = false;
      if (!isFunction$1(comp)) {
        const extendEmits = (raw2) => {
          const normalizedFromExtend = normalizeEmitsOptions(raw2, appContext, true);
          if (normalizedFromExtend) {
            hasExtends = true;
            extend(normalized, normalizedFromExtend);
          }
        };
        if (!asMixin && appContext.mixins.length) {
          appContext.mixins.forEach(extendEmits);
        }
        if (comp.extends) {
          extendEmits(comp.extends);
        }
        if (comp.mixins) {
          comp.mixins.forEach(extendEmits);
        }
      }
      if (!raw && !hasExtends) {
        if (isObject$1(comp)) {
          cache.set(comp, null);
        }
        return null;
      }
      if (isArray$1(raw)) {
        raw.forEach((key) => normalized[key] = null);
      } else {
        extend(normalized, raw);
      }
      if (isObject$1(comp)) {
        cache.set(comp, normalized);
      }
      return normalized;
    }
    function isEmitListener(options, key) {
      if (!options || !isOn(key)) {
        return false;
      }
      key = key.slice(2);
      key = key === "Once" ? key : key.replace(/Once$/, "");
      return hasOwn(options, key[0].toLowerCase() + key.slice(1)) || hasOwn(options, hyphenate(key)) || hasOwn(options, key);
    }
    function markAttrsAccessed() {
    }
    function renderComponentRoot(instance) {
      const {
        type: Component,
        vnode,
        proxy,
        withProxy,
        propsOptions: [propsOptions],
        slots,
        attrs,
        emit: emit2,
        render: render2,
        renderCache,
        props,
        data,
        setupState,
        ctx,
        inheritAttrs
      } = instance;
      const prev = setCurrentRenderingInstance(instance);
      let result;
      let fallthroughAttrs;
      try {
        if (vnode.shapeFlag & 4) {
          const proxyToUse = withProxy || proxy;
          const thisProxy = false ? new Proxy(proxyToUse, {
            get(target, key, receiver) {
              warn$1(
                `Property '${String(
                  key
                )}' was accessed via 'this'. Avoid using 'this' in templates.`
              );
              return Reflect.get(target, key, receiver);
            }
          }) : proxyToUse;
          result = normalizeVNode$1(
            render2.call(
              thisProxy,
              proxyToUse,
              renderCache,
              false ? /* @__PURE__ */ shallowReadonly(props) : props,
              setupState,
              data,
              ctx
            )
          );
          fallthroughAttrs = attrs;
        } else {
          const render22 = Component;
          if (false) ;
          result = normalizeVNode$1(
            render22.length > 1 ? render22(
              false ? /* @__PURE__ */ shallowReadonly(props) : props,
              false ? {
                get attrs() {
                  markAttrsAccessed();
                  return /* @__PURE__ */ shallowReadonly(attrs);
                },
                slots,
                emit: emit2
              } : { attrs, slots, emit: emit2 }
            ) : render22(
              false ? /* @__PURE__ */ shallowReadonly(props) : props,
              null
            )
          );
          fallthroughAttrs = Component.props ? attrs : getFunctionalFallthrough(attrs);
        }
      } catch (err) {
        blockStack.length = 0;
        handleError(err, instance, 1);
        result = createVNode(Comment);
      }
      let root2 = result;
      if (fallthroughAttrs && inheritAttrs !== false) {
        const keys = Object.keys(fallthroughAttrs);
        const { shapeFlag } = root2;
        if (keys.length) {
          if (shapeFlag & (1 | 6)) {
            if (propsOptions && keys.some(isModelListener)) {
              fallthroughAttrs = filterModelListeners(
                fallthroughAttrs,
                propsOptions
              );
            }
            root2 = cloneVNode(root2, fallthroughAttrs, false, true);
          }
        }
      }
      if (vnode.dirs) {
        root2 = cloneVNode(root2, null, false, true);
        root2.dirs = root2.dirs ? root2.dirs.concat(vnode.dirs) : vnode.dirs;
      }
      if (vnode.transition) {
        const child = isTeleport(root2.type) ? getInnerChild$1(root2) || root2 : root2;
        setTransitionHooks(child, vnode.transition);
      }
      {
        result = root2;
      }
      setCurrentRenderingInstance(prev);
      return result;
    }
    const getFunctionalFallthrough = (attrs) => {
      let res;
      for (const key in attrs) {
        if (key === "class" || key === "style" || isOn(key)) {
          (res || (res = {}))[key] = attrs[key];
        }
      }
      return res;
    };
    const filterModelListeners = (attrs, props) => {
      const res = {};
      for (const key in attrs) {
        if (!isModelListener(key) || !(key.slice(9) in props)) {
          res[key] = attrs[key];
        }
      }
      return res;
    };
    function shouldUpdateComponent(prevVNode, nextVNode, optimized) {
      const { props: prevProps, children: prevChildren, component } = prevVNode;
      const { props: nextProps, children: nextChildren, patchFlag } = nextVNode;
      const emits = component.emitsOptions;
      if (nextVNode.dirs || nextVNode.transition) {
        return true;
      }
      if (optimized && patchFlag >= 0) {
        if (patchFlag & 1024) {
          return true;
        }
        if (patchFlag & 16) {
          if (!prevProps) {
            return !!nextProps;
          }
          return hasPropsChanged(prevProps, nextProps, emits);
        } else if (patchFlag & 8) {
          const dynamicProps = nextVNode.dynamicProps;
          for (let i = 0; i < dynamicProps.length; i++) {
            const key = dynamicProps[i];
            if (hasPropValueChanged(nextProps, prevProps, key) && !isEmitListener(emits, key)) {
              return true;
            }
          }
        }
      } else {
        if (prevChildren || nextChildren) {
          if (!nextChildren || !nextChildren.$stable) {
            return true;
          }
        }
        if (prevProps === nextProps) {
          return false;
        }
        if (!prevProps) {
          return !!nextProps;
        }
        if (!nextProps) {
          return true;
        }
        return hasPropsChanged(prevProps, nextProps, emits);
      }
      return false;
    }
    function hasPropsChanged(prevProps, nextProps, emitsOptions) {
      const nextKeys = Object.keys(nextProps);
      if (nextKeys.length !== Object.keys(prevProps).length) {
        return true;
      }
      for (let i = 0; i < nextKeys.length; i++) {
        const key = nextKeys[i];
        if (hasPropValueChanged(nextProps, prevProps, key) && !isEmitListener(emitsOptions, key)) {
          return true;
        }
      }
      return false;
    }
    function hasPropValueChanged(nextProps, prevProps, key) {
      const nextProp = nextProps[key];
      const prevProp = prevProps[key];
      if (key === "style" && isObject$1(nextProp) && isObject$1(prevProp)) {
        return !looseEqual(nextProp, prevProp);
      }
      return nextProp !== prevProp;
    }
    function updateHOCHostEl({ vnode, parent, suspense }, el) {
      while (parent) {
        const root2 = parent.subTree;
        if (root2.suspense && root2.suspense.activeBranch === vnode) {
          root2.suspense.vnode.el = root2.el = el;
          vnode = root2;
        }
        if (root2 === vnode) {
          (vnode = parent.vnode).el = el;
          parent = parent.parent;
        } else {
          break;
        }
      }
      if (suspense && suspense.activeBranch === vnode) {
        suspense.vnode.el = el;
      }
    }
    const internalObjectProto = {};
    const createInternalObject = () => Object.create(internalObjectProto);
    const isInternalObject = (obj) => Object.getPrototypeOf(obj) === internalObjectProto;
    function initProps(instance, rawProps, isStateful, isSSR = false) {
      const props = {};
      const attrs = createInternalObject();
      instance.propsDefaults = /* @__PURE__ */ Object.create(null);
      setFullProps(instance, rawProps, props, attrs);
      for (const key in instance.propsOptions[0]) {
        if (!(key in props)) {
          props[key] = void 0;
        }
      }
      if (isStateful) {
        instance.props = isSSR ? props : /* @__PURE__ */ shallowReactive(props);
      } else {
        if (!instance.type.props) {
          instance.props = attrs;
        } else {
          instance.props = props;
        }
      }
      instance.attrs = attrs;
    }
    function updateProps(instance, rawProps, rawPrevProps, optimized) {
      const {
        props,
        attrs,
        vnode: { patchFlag }
      } = instance;
      const rawCurrentProps = /* @__PURE__ */ toRaw(props);
      const [options] = instance.propsOptions;
      let hasAttrsChanged = false;
      if (
        // always force full diff in dev
        // - #1942 if hmr is enabled with sfc component
        // - vite#872 non-sfc component used by sfc component
        (optimized || patchFlag > 0) && !(patchFlag & 16)
      ) {
        if (patchFlag & 8) {
          const propsToUpdate = instance.vnode.dynamicProps;
          for (let i = 0; i < propsToUpdate.length; i++) {
            let key = propsToUpdate[i];
            if (isEmitListener(instance.emitsOptions, key)) {
              continue;
            }
            const value = rawProps[key];
            if (options) {
              if (hasOwn(attrs, key)) {
                if (value !== attrs[key]) {
                  attrs[key] = value;
                  hasAttrsChanged = true;
                }
              } else {
                const camelizedKey = camelize(key);
                props[camelizedKey] = resolvePropValue(
                  options,
                  rawCurrentProps,
                  camelizedKey,
                  value,
                  instance,
                  false
                );
              }
            } else {
              if (value !== attrs[key]) {
                attrs[key] = value;
                hasAttrsChanged = true;
              }
            }
          }
        }
      } else {
        if (setFullProps(instance, rawProps, props, attrs)) {
          hasAttrsChanged = true;
        }
        let kebabKey;
        for (const key in rawCurrentProps) {
          if (!rawProps || // for camelCase
          !hasOwn(rawProps, key) && // it's possible the original props was passed in as kebab-case
          // and converted to camelCase (#955)
          ((kebabKey = hyphenate(key)) === key || !hasOwn(rawProps, kebabKey))) {
            if (options) {
              if (rawPrevProps && // for camelCase
              (rawPrevProps[key] !== void 0 || // for kebab-case
              rawPrevProps[kebabKey] !== void 0)) {
                props[key] = resolvePropValue(
                  options,
                  rawCurrentProps,
                  key,
                  void 0,
                  instance,
                  true
                );
              }
            } else {
              delete props[key];
            }
          }
        }
        if (attrs !== rawCurrentProps) {
          for (const key in attrs) {
            if (!rawProps || !hasOwn(rawProps, key) && true) {
              delete attrs[key];
              hasAttrsChanged = true;
            }
          }
        }
      }
      if (hasAttrsChanged) {
        trigger(instance.attrs, "set", "");
      }
    }
    function setFullProps(instance, rawProps, props, attrs) {
      const [options, needCastKeys] = instance.propsOptions;
      let hasAttrsChanged = false;
      let rawCastValues;
      if (rawProps) {
        for (let key in rawProps) {
          if (isReservedProp(key)) {
            continue;
          }
          const value = rawProps[key];
          let camelKey;
          if (options && hasOwn(options, camelKey = camelize(key))) {
            if (!needCastKeys || !needCastKeys.includes(camelKey)) {
              props[camelKey] = value;
            } else {
              (rawCastValues || (rawCastValues = {}))[camelKey] = value;
            }
          } else if (!isEmitListener(instance.emitsOptions, key)) {
            if (!(key in attrs) || value !== attrs[key]) {
              attrs[key] = value;
              hasAttrsChanged = true;
            }
          }
        }
      }
      if (needCastKeys) {
        const rawCurrentProps = /* @__PURE__ */ toRaw(props);
        const castValues = rawCastValues || EMPTY_OBJ;
        for (let i = 0; i < needCastKeys.length; i++) {
          const key = needCastKeys[i];
          props[key] = resolvePropValue(
            options,
            rawCurrentProps,
            key,
            castValues[key],
            instance,
            !hasOwn(castValues, key)
          );
        }
      }
      return hasAttrsChanged;
    }
    function resolvePropValue(options, props, key, value, instance, isAbsent) {
      const opt = options[key];
      if (opt != null) {
        const hasDefault = hasOwn(opt, "default");
        if (hasDefault && value === void 0) {
          const defaultValue = opt.default;
          if (opt.type !== Function && !opt.skipFactory && isFunction$1(defaultValue)) {
            const { propsDefaults } = instance;
            if (key in propsDefaults) {
              value = propsDefaults[key];
            } else {
              const reset = setCurrentInstance(instance);
              value = propsDefaults[key] = defaultValue.call(
                null,
                props
              );
              reset();
            }
          } else {
            value = defaultValue;
          }
          if (instance.ce) {
            instance.ce._setProp(key, value);
          }
        }
        if (opt[
          0
          /* shouldCast */
        ]) {
          if (isAbsent && !hasDefault) {
            value = false;
          } else if (opt[
            1
            /* shouldCastTrue */
          ] && (value === "" || value === hyphenate(key))) {
            value = true;
          }
        }
      }
      return value;
    }
    const mixinPropsCache = /* @__PURE__ */ new WeakMap();
    function normalizePropsOptions(comp, appContext, asMixin = false) {
      const cache = asMixin ? mixinPropsCache : appContext.propsCache;
      const cached = cache.get(comp);
      if (cached) {
        return cached;
      }
      const raw = comp.props;
      const normalized = {};
      const needCastKeys = [];
      let hasExtends = false;
      if (!isFunction$1(comp)) {
        const extendProps = (raw2) => {
          hasExtends = true;
          const [props, keys] = normalizePropsOptions(raw2, appContext, true);
          extend(normalized, props);
          if (keys) needCastKeys.push(...keys);
        };
        if (!asMixin && appContext.mixins.length) {
          appContext.mixins.forEach(extendProps);
        }
        if (comp.extends) {
          extendProps(comp.extends);
        }
        if (comp.mixins) {
          comp.mixins.forEach(extendProps);
        }
      }
      if (!raw && !hasExtends) {
        if (isObject$1(comp)) {
          cache.set(comp, EMPTY_ARR);
        }
        return EMPTY_ARR;
      }
      if (isArray$1(raw)) {
        for (let i = 0; i < raw.length; i++) {
          const normalizedKey = camelize(raw[i]);
          if (validatePropName(normalizedKey)) {
            normalized[normalizedKey] = EMPTY_OBJ;
          }
        }
      } else if (raw) {
        for (const key in raw) {
          const normalizedKey = camelize(key);
          if (validatePropName(normalizedKey)) {
            const opt = raw[key];
            const prop = normalized[normalizedKey] = isArray$1(opt) || isFunction$1(opt) ? { type: opt } : extend({}, opt);
            const propType = prop.type;
            let shouldCast = false;
            let shouldCastTrue = true;
            if (isArray$1(propType)) {
              for (let index = 0; index < propType.length; ++index) {
                const type = propType[index];
                const typeName = isFunction$1(type) && type.name;
                if (typeName === "Boolean") {
                  shouldCast = true;
                  break;
                } else if (typeName === "String") {
                  shouldCastTrue = false;
                }
              }
            } else {
              shouldCast = isFunction$1(propType) && propType.name === "Boolean";
            }
            prop[
              0
              /* shouldCast */
            ] = shouldCast;
            prop[
              1
              /* shouldCastTrue */
            ] = shouldCastTrue;
            if (shouldCast || hasOwn(prop, "default")) {
              needCastKeys.push(normalizedKey);
            }
          }
        }
      }
      const res = [normalized, needCastKeys];
      if (isObject$1(comp)) {
        cache.set(comp, res);
      }
      return res;
    }
    function validatePropName(key) {
      if (key[0] !== "$" && !isReservedProp(key)) {
        return true;
      }
      return false;
    }
    const isInternalKey = (key) => key === "_" || key === "_ctx" || key === "$stable";
    const normalizeSlotValue = (value) => isArray$1(value) ? value.map(normalizeVNode$1) : [normalizeVNode$1(value)];
    const normalizeSlot = (key, rawSlot, ctx) => {
      if (rawSlot._n) {
        return rawSlot;
      }
      const normalized = withCtx((...args) => {
        if (false) ;
        return normalizeSlotValue(rawSlot(...args));
      }, ctx);
      normalized._c = false;
      return normalized;
    };
    const normalizeObjectSlots = (rawSlots, slots, instance) => {
      const ctx = rawSlots._ctx;
      for (const key in rawSlots) {
        if (isInternalKey(key)) continue;
        const value = rawSlots[key];
        if (isFunction$1(value)) {
          slots[key] = normalizeSlot(key, value, ctx);
        } else if (value != null) {
          const normalized = normalizeSlotValue(value);
          slots[key] = () => normalized;
        }
      }
    };
    const normalizeVNodeSlots = (instance, children) => {
      const normalized = normalizeSlotValue(children);
      instance.slots.default = () => normalized;
    };
    const assignSlots = (slots, children, optimized) => {
      for (const key in children) {
        if (optimized || !isInternalKey(key)) {
          slots[key] = children[key];
        }
      }
    };
    const initSlots = (instance, children, optimized) => {
      const slots = instance.slots = createInternalObject();
      if (instance.vnode.shapeFlag & 32) {
        const type = children._;
        if (type) {
          assignSlots(slots, children, optimized);
          if (optimized) {
            def(slots, "_", type, true);
          }
        } else {
          normalizeObjectSlots(children, slots);
        }
      } else if (children) {
        normalizeVNodeSlots(instance, children);
      }
    };
    const updateSlots = (instance, children, optimized) => {
      const { vnode, slots } = instance;
      let needDeletionCheck = true;
      let deletionComparisonTarget = EMPTY_OBJ;
      if (vnode.shapeFlag & 32) {
        const type = children._;
        if (type) {
          if (optimized && type === 1) {
            needDeletionCheck = false;
          } else {
            assignSlots(slots, children, optimized);
          }
        } else {
          needDeletionCheck = !children.$stable;
          normalizeObjectSlots(children, slots);
        }
        deletionComparisonTarget = children;
      } else if (children) {
        normalizeVNodeSlots(instance, children);
        deletionComparisonTarget = { default: 1 };
      }
      if (needDeletionCheck) {
        for (const key in slots) {
          if (!isInternalKey(key) && deletionComparisonTarget[key] == null) {
            delete slots[key];
          }
        }
      }
    };
    const queuePostRenderEffect = queueEffectWithSuspense;
    function createRenderer(options) {
      return baseCreateRenderer(options);
    }
    function baseCreateRenderer(options, createHydrationFns) {
      const target = getGlobalThis();
      target.__VUE__ = true;
      const {
        insert: hostInsert,
        remove: hostRemove,
        patchProp: hostPatchProp,
        createElement: hostCreateElement,
        createText: hostCreateText,
        createComment: hostCreateComment,
        setText: hostSetText,
        setElementText: hostSetElementText,
        parentNode: hostParentNode,
        nextSibling: hostNextSibling,
        setScopeId: hostSetScopeId = NOOP,
        insertStaticContent: hostInsertStaticContent
      } = options;
      const patch = (n1, n2, container, anchor = null, parentComponent = null, parentSuspense = null, namespace = void 0, slotScopeIds = null, optimized = !!n2.dynamicChildren) => {
        if (n1 === n2) {
          return;
        }
        if (n1 && !isSameVNodeType(n1, n2)) {
          anchor = getNextHostNode(n1);
          unmount2(n1, parentComponent, parentSuspense, true);
          n1 = null;
        }
        if (n2.patchFlag === -2) {
          optimized = false;
          n2.dynamicChildren = null;
        }
        if (n2.dynamicChildren && n1 && n1.dynamicChildren && n1.dynamicChildren.hasOnce) {
          if (n2.dynamicChildren === EMPTY_ARR) {
            n2.dynamicChildren = [];
          }
          n2.dynamicChildren.hasOnce = true;
        }
        const { type, ref: ref3, shapeFlag } = n2;
        switch (type) {
          case Text:
            processText(n1, n2, container, anchor);
            break;
          case Comment:
            processCommentNode(n1, n2, container, anchor);
            break;
          case Static:
            if (n1 == null) {
              mountStaticNode(n2, container, anchor, namespace);
            }
            break;
          case Fragment:
            processFragment(
              n1,
              n2,
              container,
              anchor,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds,
              optimized
            );
            break;
          default:
            if (shapeFlag & 1) {
              processElement(
                n1,
                n2,
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized
              );
            } else if (shapeFlag & 6) {
              processComponent(
                n1,
                n2,
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized
              );
            } else if (shapeFlag & 64) {
              type.process(
                n1,
                n2,
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized,
                internals
              );
            } else if (shapeFlag & 128) {
              type.process(
                n1,
                n2,
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized,
                internals
              );
            } else ;
        }
        if (ref3 != null && parentComponent) {
          setRef(ref3, n1 && n1.ref, parentSuspense, n2 || n1, !n2);
        } else if (ref3 == null && n1 && n1.ref != null) {
          setRef(n1.ref, null, parentSuspense, n1, true);
        }
      };
      const processText = (n1, n2, container, anchor) => {
        if (n1 == null) {
          hostInsert(
            n2.el = hostCreateText(n2.children),
            container,
            anchor
          );
        } else {
          const el = n2.el = n1.el;
          if (n2.children !== n1.children) {
            hostSetText(el, n2.children);
          }
        }
      };
      const processCommentNode = (n1, n2, container, anchor) => {
        if (n1 == null) {
          hostInsert(
            n2.el = hostCreateComment(n2.children || ""),
            container,
            anchor
          );
        } else {
          n2.el = n1.el;
        }
      };
      const mountStaticNode = (n2, container, anchor, namespace) => {
        [n2.el, n2.anchor] = hostInsertStaticContent(
          n2.children,
          container,
          anchor,
          namespace,
          n2.el,
          n2.anchor
        );
      };
      const moveStaticNode = ({ el, anchor }, container, nextSibling) => {
        let next;
        while (el && el !== anchor) {
          next = hostNextSibling(el);
          hostInsert(el, container, nextSibling);
          el = next;
        }
        hostInsert(anchor, container, nextSibling);
      };
      const removeStaticNode = ({ el, anchor }) => {
        let next;
        while (el && el !== anchor) {
          next = hostNextSibling(el);
          hostRemove(el);
          el = next;
        }
        hostRemove(anchor);
      };
      const processElement = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
        if (n2.type === "svg") {
          namespace = "svg";
        } else if (n2.type === "math") {
          namespace = "mathml";
        }
        if (n1 == null) {
          mountElement(
            n2,
            container,
            anchor,
            parentComponent,
            parentSuspense,
            namespace,
            slotScopeIds,
            optimized
          );
        } else {
          const customElement = n1.el && n1.el._isVueCE ? n1.el : null;
          try {
            if (customElement) {
              customElement._beginPatch();
            }
            patchElement(
              n1,
              n2,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds,
              optimized
            );
          } finally {
            if (customElement) {
              customElement._endPatch();
            }
          }
        }
      };
      const mountElement = (vnode, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
        let el;
        let vnodeHook;
        const { props, shapeFlag, transition, dirs } = vnode;
        el = vnode.el = hostCreateElement(
          vnode.type,
          namespace,
          props && props.is,
          props
        );
        if (shapeFlag & 8) {
          hostSetElementText(el, vnode.children);
        } else if (shapeFlag & 16) {
          mountChildren(
            vnode.children,
            el,
            null,
            parentComponent,
            parentSuspense,
            resolveChildrenNamespace(vnode, namespace),
            slotScopeIds,
            optimized
          );
        }
        if (dirs) {
          invokeDirectiveHook(vnode, null, parentComponent, "created");
        }
        setScopeId(el, vnode, vnode.scopeId, slotScopeIds, parentComponent);
        if (props) {
          for (const key in props) {
            if (key !== "value" && !isReservedProp(key)) {
              hostPatchProp(el, key, null, props[key], namespace, parentComponent);
            }
          }
          if ("value" in props) {
            hostPatchProp(el, "value", null, props.value, namespace);
          }
          if (vnodeHook = props.onVnodeBeforeMount) {
            invokeVNodeHook(vnodeHook, parentComponent, vnode);
          }
        }
        if (dirs) {
          invokeDirectiveHook(vnode, null, parentComponent, "beforeMount");
        }
        const needCallTransitionHooks = needTransition(parentSuspense, transition);
        if (needCallTransitionHooks) {
          transition.beforeEnter(el);
        }
        hostInsert(el, container, anchor);
        if ((vnodeHook = props && props.onVnodeMounted) || needCallTransitionHooks || dirs) {
          queuePostRenderEffect(() => {
            try {
              vnodeHook && invokeVNodeHook(vnodeHook, parentComponent, vnode);
              needCallTransitionHooks && transition.enter(el);
              dirs && invokeDirectiveHook(vnode, null, parentComponent, "mounted");
            } finally {
            }
          }, parentSuspense);
        }
      };
      const setScopeId = (el, vnode, scopeId, slotScopeIds, parentComponent) => {
        if (scopeId) {
          hostSetScopeId(el, scopeId);
        }
        if (slotScopeIds) {
          for (let i = 0; i < slotScopeIds.length; i++) {
            hostSetScopeId(el, slotScopeIds[i]);
          }
        }
        if (parentComponent) {
          let subTree = parentComponent.subTree;
          if (vnode === subTree || isSuspense(subTree.type) && (subTree.ssContent === vnode || subTree.ssFallback === vnode)) {
            const parentVNode = parentComponent.vnode;
            setScopeId(
              el,
              parentVNode,
              parentVNode.scopeId,
              parentVNode.slotScopeIds,
              parentComponent.parent
            );
          }
        }
      };
      const mountChildren = (children, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized, start = 0) => {
        for (let i = start; i < children.length; i++) {
          const child = children[i] = optimized ? cloneIfMounted$1(children[i]) : normalizeVNode$1(children[i]);
          patch(
            null,
            child,
            container,
            anchor,
            parentComponent,
            parentSuspense,
            namespace,
            slotScopeIds,
            optimized
          );
        }
      };
      const patchElement = (n1, n2, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
        const el = n2.el = n1.el;
        let { patchFlag, dynamicChildren, dirs } = n2;
        patchFlag |= n1.patchFlag & 16;
        const oldProps = n1.props || EMPTY_OBJ;
        const newProps = n2.props || EMPTY_OBJ;
        let vnodeHook;
        parentComponent && toggleRecurse(parentComponent, false);
        if (vnodeHook = newProps.onVnodeBeforeUpdate) {
          invokeVNodeHook(vnodeHook, parentComponent, n2, n1);
        }
        if (dirs) {
          invokeDirectiveHook(n2, n1, parentComponent, "beforeUpdate");
        }
        parentComponent && toggleRecurse(parentComponent, true);
        if (
          // #6385 the old vnode may be a user-wrapped non-isomorphic block
          // Force full diff when block metadata is unstable.
          dynamicChildren && (!n1.dynamicChildren || n1.dynamicChildren.length !== dynamicChildren.length)
        ) {
          patchFlag = 0;
          optimized = false;
          dynamicChildren = null;
        }
        if (oldProps.innerHTML && newProps.innerHTML == null || oldProps.textContent && newProps.textContent == null) {
          hostSetElementText(el, "");
        }
        if (dynamicChildren) {
          patchBlockChildren(
            n1.dynamicChildren,
            dynamicChildren,
            el,
            parentComponent,
            parentSuspense,
            resolveChildrenNamespace(n2, namespace),
            slotScopeIds
          );
        } else if (!optimized) {
          patchChildren(
            n1,
            n2,
            el,
            null,
            parentComponent,
            parentSuspense,
            resolveChildrenNamespace(n2, namespace),
            slotScopeIds,
            false
          );
        }
        if (patchFlag > 0) {
          if (patchFlag & 16) {
            patchProps(el, oldProps, newProps, parentComponent, namespace);
          } else {
            if (patchFlag & 2) {
              if (oldProps.class !== newProps.class) {
                hostPatchProp(el, "class", null, newProps.class, namespace);
              }
            }
            if (patchFlag & 4) {
              hostPatchProp(el, "style", oldProps.style, newProps.style, namespace);
            }
            if (patchFlag & 8) {
              const propsToUpdate = n2.dynamicProps;
              for (let i = 0; i < propsToUpdate.length; i++) {
                const key = propsToUpdate[i];
                const prev = oldProps[key];
                const next = newProps[key];
                if (next !== prev || key === "value") {
                  hostPatchProp(el, key, prev, next, namespace, parentComponent);
                }
              }
            }
          }
          if (patchFlag & 1) {
            if (n1.children !== n2.children) {
              hostSetElementText(el, n2.children);
            }
          }
        } else if (!optimized && dynamicChildren == null) {
          patchProps(el, oldProps, newProps, parentComponent, namespace);
        }
        if ((vnodeHook = newProps.onVnodeUpdated) || dirs) {
          queuePostRenderEffect(() => {
            vnodeHook && invokeVNodeHook(vnodeHook, parentComponent, n2, n1);
            dirs && invokeDirectiveHook(n2, n1, parentComponent, "updated");
          }, parentSuspense);
        }
      };
      const patchBlockChildren = (oldChildren, newChildren, fallbackContainer, parentComponent, parentSuspense, namespace, slotScopeIds) => {
        for (let i = 0; i < newChildren.length; i++) {
          const oldVNode = oldChildren[i];
          const newVNode = newChildren[i];
          const container = (
            // oldVNode may be an errored async setup() component inside Suspense
            // which will not have a mounted element
            oldVNode.el && // - In the case of a Fragment, we need to provide the actual parent
            // of the Fragment itself so it can move its children.
            (oldVNode.type === Fragment || // - In the case of different nodes, there is going to be a replacement
            // which also requires the correct parent container
            !isSameVNodeType(oldVNode, newVNode) || // - In the case of a component, it could contain anything.
            oldVNode.shapeFlag & (6 | 64 | 128)) ? hostParentNode(oldVNode.el) : (
              // In other cases, the parent container is not actually used so we
              // just pass the block element here to avoid a DOM parentNode call.
              fallbackContainer
            )
          );
          patch(
            oldVNode,
            newVNode,
            container,
            null,
            parentComponent,
            parentSuspense,
            namespace,
            slotScopeIds,
            true
          );
        }
      };
      const patchProps = (el, oldProps, newProps, parentComponent, namespace) => {
        if (oldProps !== newProps) {
          if (oldProps !== EMPTY_OBJ) {
            for (const key in oldProps) {
              if (!isReservedProp(key) && !(key in newProps)) {
                hostPatchProp(
                  el,
                  key,
                  oldProps[key],
                  null,
                  namespace,
                  parentComponent
                );
              }
            }
          }
          for (const key in newProps) {
            if (isReservedProp(key)) continue;
            const next = newProps[key];
            const prev = oldProps[key];
            if (next !== prev && key !== "value") {
              hostPatchProp(el, key, prev, next, namespace, parentComponent);
            }
          }
          if ("value" in newProps) {
            hostPatchProp(el, "value", oldProps.value, newProps.value, namespace);
          }
        }
      };
      const processFragment = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
        const fragmentStartAnchor = n2.el = n1 ? n1.el : hostCreateText("");
        const fragmentEndAnchor = n2.anchor = n1 ? n1.anchor : hostCreateText("");
        let { patchFlag, dynamicChildren, slotScopeIds: fragmentSlotScopeIds } = n2;
        if (fragmentSlotScopeIds) {
          slotScopeIds = slotScopeIds ? slotScopeIds.concat(fragmentSlotScopeIds) : fragmentSlotScopeIds;
        }
        if (n1 == null) {
          hostInsert(fragmentStartAnchor, container, anchor);
          hostInsert(fragmentEndAnchor, container, anchor);
          mountChildren(
            // #10007
            // such fragment like `<></>` will be compiled into
            // a fragment which doesn't have a children.
            // In this case fallback to an empty array
            n2.children || [],
            container,
            fragmentEndAnchor,
            parentComponent,
            parentSuspense,
            namespace,
            slotScopeIds,
            optimized
          );
        } else {
          if (patchFlag > 0 && patchFlag & 64 && dynamicChildren && // #2715 the previous fragment could've been a BAILed one as a result
          // of renderSlot() with no valid children
          n1.dynamicChildren && n1.dynamicChildren.length === dynamicChildren.length) {
            patchBlockChildren(
              n1.dynamicChildren,
              dynamicChildren,
              container,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds
            );
            if (
              // #2080 if the stable fragment has a key, it's a <template v-for> that may
              //  get moved around. Make sure all root level vnodes inherit el.
              // #2134 or if it's a component root, it may also get moved around
              // as the component is being moved.
              n2.key != null || parentComponent && n2 === parentComponent.subTree
            ) {
              traverseStaticChildren(
                n1,
                n2,
                true
                /* shallow */
              );
            }
          } else {
            patchChildren(
              n1,
              n2,
              container,
              fragmentEndAnchor,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds,
              optimized
            );
          }
        }
      };
      const processComponent = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
        n2.slotScopeIds = slotScopeIds;
        if (n1 == null) {
          if (n2.shapeFlag & 512) {
            parentComponent.ctx.activate(
              n2,
              container,
              anchor,
              namespace,
              optimized
            );
          } else {
            mountComponent(
              n2,
              container,
              anchor,
              parentComponent,
              parentSuspense,
              namespace,
              optimized
            );
          }
        } else {
          updateComponent(n1, n2, optimized);
        }
      };
      const mountComponent = (initialVNode, container, anchor, parentComponent, parentSuspense, namespace, optimized) => {
        const instance = initialVNode.component = createComponentInstance(
          initialVNode,
          parentComponent,
          parentSuspense
        );
        if (isKeepAlive(initialVNode)) {
          instance.ctx.renderer = internals;
        }
        {
          setupComponent(instance, false, optimized);
        }
        if (instance.asyncDep) {
          parentSuspense && parentSuspense.registerDep(instance, setupRenderEffect, optimized);
          if (!initialVNode.el) {
            const placeholder = instance.subTree = createVNode(Comment);
            processCommentNode(null, placeholder, container, anchor);
            initialVNode.placeholder = placeholder.el;
          }
        } else {
          setupRenderEffect(
            instance,
            initialVNode,
            container,
            anchor,
            parentSuspense,
            namespace,
            optimized
          );
        }
      };
      const updateComponent = (n1, n2, optimized) => {
        const instance = n2.component = n1.component;
        if (shouldUpdateComponent(n1, n2, optimized)) {
          if (instance.asyncDep && !instance.asyncResolved) {
            n2.el = n1.el;
            updateComponentPreRender(instance, n2, optimized);
            return;
          } else {
            instance.next = n2;
            instance.update();
          }
        } else {
          n2.el = n1.el;
          instance.vnode = n2;
        }
      };
      const setupRenderEffect = (instance, initialVNode, container, anchor, parentSuspense, namespace, optimized) => {
        const componentUpdateFn = () => {
          if (!instance.isMounted) {
            let vnodeHook;
            const { el, props } = initialVNode;
            const { bm, m, parent, root: root2, type } = instance;
            const isAsyncWrapperVNode = isAsyncWrapper(initialVNode);
            toggleRecurse(instance, false);
            if (bm) {
              invokeArrayFns(bm);
            }
            if (!isAsyncWrapperVNode && (vnodeHook = props && props.onVnodeBeforeMount)) {
              invokeVNodeHook(vnodeHook, parent, initialVNode);
            }
            toggleRecurse(instance, true);
            {
              if (root2.ce && root2.ce._hasShadowRoot()) {
                root2.ce._injectChildStyle(
                  type,
                  instance.parent ? instance.parent.type : void 0
                );
              }
              const subTree = instance.subTree = renderComponentRoot(instance);
              patch(
                null,
                subTree,
                container,
                anchor,
                instance,
                parentSuspense,
                namespace
              );
              initialVNode.el = subTree.el;
            }
            if (m) {
              queuePostRenderEffect(m, parentSuspense);
            }
            if (!isAsyncWrapperVNode && (vnodeHook = props && props.onVnodeMounted)) {
              const scopedInitialVNode = initialVNode;
              queuePostRenderEffect(
                () => invokeVNodeHook(vnodeHook, parent, scopedInitialVNode),
                parentSuspense
              );
            }
            if (initialVNode.shapeFlag & 256 || parent && isAsyncWrapper(parent.vnode) && parent.vnode.shapeFlag & 256) {
              instance.a && queuePostRenderEffect(instance.a, parentSuspense);
            }
            instance.isMounted = true;
            initialVNode = container = anchor = null;
          } else {
            let { next, bu, u, parent, vnode } = instance;
            {
              const nonHydratedAsyncRoot = locateNonHydratedAsyncRoot(instance);
              if (nonHydratedAsyncRoot) {
                if (next) {
                  next.el = vnode.el;
                  updateComponentPreRender(instance, next, optimized);
                }
                nonHydratedAsyncRoot.asyncDep.then(() => {
                  queuePostRenderEffect(() => {
                    if (!instance.isUnmounted) update();
                  }, parentSuspense);
                });
                return;
              }
            }
            let originNext = next;
            let vnodeHook;
            toggleRecurse(instance, false);
            if (next) {
              next.el = vnode.el;
              updateComponentPreRender(instance, next, optimized);
            } else {
              next = vnode;
            }
            if (bu) {
              invokeArrayFns(bu);
            }
            if (vnodeHook = next.props && next.props.onVnodeBeforeUpdate) {
              invokeVNodeHook(vnodeHook, parent, next, vnode);
            }
            toggleRecurse(instance, true);
            const nextTree = renderComponentRoot(instance);
            const prevTree = instance.subTree;
            instance.subTree = nextTree;
            patch(
              prevTree,
              nextTree,
              // parent may have changed if it's in a teleport
              hostParentNode(prevTree.el),
              // anchor may have changed if it's in a fragment
              getNextHostNode(prevTree),
              instance,
              parentSuspense,
              namespace
            );
            next.el = nextTree.el;
            if (originNext === null) {
              updateHOCHostEl(instance, nextTree.el);
            }
            if (u) {
              queuePostRenderEffect(u, parentSuspense);
            }
            if (vnodeHook = next.props && next.props.onVnodeUpdated) {
              queuePostRenderEffect(
                () => invokeVNodeHook(vnodeHook, parent, next, vnode),
                parentSuspense
              );
            }
          }
        };
        instance.scope.on();
        const effect2 = instance.effect = new ReactiveEffect(componentUpdateFn);
        instance.scope.off();
        const update = instance.update = effect2.run.bind(effect2);
        const job = instance.job = effect2.runIfDirty.bind(effect2);
        job.i = instance;
        job.id = instance.uid;
        effect2.scheduler = () => queueJob(job);
        toggleRecurse(instance, true);
        update();
      };
      const updateComponentPreRender = (instance, nextVNode, optimized) => {
        nextVNode.component = instance;
        const prevProps = instance.vnode.props;
        instance.vnode = nextVNode;
        instance.next = null;
        updateProps(instance, nextVNode.props, prevProps, optimized);
        updateSlots(instance, nextVNode.children, optimized);
        pauseTracking();
        flushPreFlushCbs(instance);
        resetTracking();
      };
      const patchChildren = (n1, n2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized = false) => {
        const c1 = n1 && n1.children;
        const prevShapeFlag = n1 ? n1.shapeFlag : 0;
        const c2 = n2.children;
        const { patchFlag, shapeFlag } = n2;
        if (patchFlag > 0) {
          if (patchFlag & 128) {
            patchKeyedChildren(
              c1,
              c2,
              container,
              anchor,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds,
              optimized
            );
            return;
          } else if (patchFlag & 256) {
            patchUnkeyedChildren(
              c1,
              c2,
              container,
              anchor,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds,
              optimized
            );
            return;
          }
        }
        if (shapeFlag & 8) {
          if (prevShapeFlag & 16) {
            unmountChildren(c1, parentComponent, parentSuspense);
          }
          if (c2 !== c1) {
            hostSetElementText(container, c2);
          }
        } else {
          if (prevShapeFlag & 16) {
            if (shapeFlag & 16) {
              patchKeyedChildren(
                c1,
                c2,
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized
              );
            } else {
              unmountChildren(c1, parentComponent, parentSuspense, true);
            }
          } else {
            if (prevShapeFlag & 8) {
              hostSetElementText(container, "");
            }
            if (shapeFlag & 16) {
              mountChildren(
                c2,
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized
              );
            }
          }
        }
      };
      const patchUnkeyedChildren = (c1, c2, container, anchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
        c1 = c1 || EMPTY_ARR;
        c2 = c2 || EMPTY_ARR;
        const oldLength = c1.length;
        const newLength = c2.length;
        const commonLength = Math.min(oldLength, newLength);
        let i;
        for (i = 0; i < commonLength; i++) {
          const nextChild = c2[i] = optimized ? cloneIfMounted$1(c2[i]) : normalizeVNode$1(c2[i]);
          patch(
            c1[i],
            nextChild,
            container,
            null,
            parentComponent,
            parentSuspense,
            namespace,
            slotScopeIds,
            optimized
          );
        }
        if (oldLength > newLength) {
          unmountChildren(
            c1,
            parentComponent,
            parentSuspense,
            true,
            false,
            commonLength
          );
        } else {
          mountChildren(
            c2,
            container,
            anchor,
            parentComponent,
            parentSuspense,
            namespace,
            slotScopeIds,
            optimized,
            commonLength
          );
        }
      };
      const patchKeyedChildren = (c1, c2, container, parentAnchor, parentComponent, parentSuspense, namespace, slotScopeIds, optimized) => {
        let i = 0;
        const l2 = c2.length;
        let e1 = c1.length - 1;
        let e2 = l2 - 1;
        while (i <= e1 && i <= e2) {
          const n1 = c1[i];
          const n2 = c2[i] = optimized ? cloneIfMounted$1(c2[i]) : normalizeVNode$1(c2[i]);
          if (isSameVNodeType(n1, n2)) {
            patch(
              n1,
              n2,
              container,
              null,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds,
              optimized
            );
          } else {
            break;
          }
          i++;
        }
        while (i <= e1 && i <= e2) {
          const n1 = c1[e1];
          const n2 = c2[e2] = optimized ? cloneIfMounted$1(c2[e2]) : normalizeVNode$1(c2[e2]);
          if (isSameVNodeType(n1, n2)) {
            patch(
              n1,
              n2,
              container,
              null,
              parentComponent,
              parentSuspense,
              namespace,
              slotScopeIds,
              optimized
            );
          } else {
            break;
          }
          e1--;
          e2--;
        }
        if (i > e1) {
          if (i <= e2) {
            const nextPos = e2 + 1;
            const anchor = nextPos < l2 ? c2[nextPos].el : parentAnchor;
            while (i <= e2) {
              patch(
                null,
                c2[i] = optimized ? cloneIfMounted$1(c2[i]) : normalizeVNode$1(c2[i]),
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized
              );
              i++;
            }
          }
        } else if (i > e2) {
          while (i <= e1) {
            unmount2(c1[i], parentComponent, parentSuspense, true);
            i++;
          }
        } else {
          const s1 = i;
          const s2 = i;
          const keyToNewIndexMap = /* @__PURE__ */ new Map();
          for (i = s2; i <= e2; i++) {
            const nextChild = c2[i] = optimized ? cloneIfMounted$1(c2[i]) : normalizeVNode$1(c2[i]);
            if (nextChild.key != null) {
              keyToNewIndexMap.set(nextChild.key, i);
            }
          }
          let j;
          let patched = 0;
          const toBePatched = e2 - s2 + 1;
          let moved = false;
          let maxNewIndexSoFar = 0;
          const newIndexToOldIndexMap = new Array(toBePatched);
          for (i = 0; i < toBePatched; i++) newIndexToOldIndexMap[i] = 0;
          for (i = s1; i <= e1; i++) {
            const prevChild = c1[i];
            if (patched >= toBePatched) {
              unmount2(prevChild, parentComponent, parentSuspense, true);
              continue;
            }
            let newIndex;
            if (prevChild.key != null) {
              newIndex = keyToNewIndexMap.get(prevChild.key);
            } else {
              for (j = s2; j <= e2; j++) {
                if (newIndexToOldIndexMap[j - s2] === 0 && isSameVNodeType(prevChild, c2[j])) {
                  newIndex = j;
                  break;
                }
              }
            }
            if (newIndex === void 0) {
              unmount2(prevChild, parentComponent, parentSuspense, true);
            } else {
              newIndexToOldIndexMap[newIndex - s2] = i + 1;
              if (newIndex >= maxNewIndexSoFar) {
                maxNewIndexSoFar = newIndex;
              } else {
                moved = true;
              }
              patch(
                prevChild,
                c2[newIndex],
                container,
                null,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized
              );
              patched++;
            }
          }
          const increasingNewIndexSequence = moved ? getSequence(newIndexToOldIndexMap) : EMPTY_ARR;
          j = increasingNewIndexSequence.length - 1;
          for (i = toBePatched - 1; i >= 0; i--) {
            const nextIndex = s2 + i;
            const nextChild = c2[nextIndex];
            const anchorVNode = c2[nextIndex + 1];
            const anchor = nextIndex + 1 < l2 ? (
              // #13559, #14173 fallback to el placeholder for unresolved async component
              anchorVNode.el || resolveAsyncComponentPlaceholder(anchorVNode)
            ) : parentAnchor;
            if (newIndexToOldIndexMap[i] === 0) {
              patch(
                null,
                nextChild,
                container,
                anchor,
                parentComponent,
                parentSuspense,
                namespace,
                slotScopeIds,
                optimized
              );
            } else if (moved) {
              if (j < 0 || i !== increasingNewIndexSequence[j]) {
                move(nextChild, container, anchor, 2);
              } else {
                j--;
              }
            }
          }
        }
      };
      const move = (vnode, container, anchor, moveType, parentSuspense = null) => {
        const { el, type, transition, children, shapeFlag } = vnode;
        if (shapeFlag & 6) {
          move(vnode.component.subTree, container, anchor, moveType);
          return;
        }
        if (shapeFlag & 128) {
          vnode.suspense.move(container, anchor, moveType);
          return;
        }
        if (shapeFlag & 64) {
          type.move(vnode, container, anchor, internals);
          return;
        }
        if (type === Fragment) {
          hostInsert(el, container, anchor);
          for (let i = 0; i < children.length; i++) {
            move(children[i], container, anchor, moveType);
          }
          hostInsert(vnode.anchor, container, anchor);
          return;
        }
        if (type === Static) {
          moveStaticNode(vnode, container, anchor);
          return;
        }
        const needTransition2 = moveType !== 2 && shapeFlag & 1 && transition;
        if (needTransition2) {
          if (moveType === 0) {
            if (transition.persisted && !el[leaveCbKey]) {
              hostInsert(el, container, anchor);
            } else {
              transition.beforeEnter(el);
              hostInsert(el, container, anchor);
              queuePostRenderEffect(() => transition.enter(el), parentSuspense);
            }
          } else {
            const { leave, delayLeave, afterLeave } = transition;
            const remove22 = () => {
              if (vnode.ctx.isUnmounted) {
                hostRemove(el);
              } else {
                hostInsert(el, container, anchor);
              }
            };
            const performLeave = () => {
              const wasLeaving = el._isLeaving || !!el[leaveCbKey];
              if (el._isLeaving) {
                el[leaveCbKey](
                  true
                  /* cancelled */
                );
              }
              if (transition.persisted && !wasLeaving) {
                remove22();
              } else {
                leave(el, () => {
                  remove22();
                  afterLeave && afterLeave();
                });
              }
            };
            if (delayLeave) {
              delayLeave(el, remove22, performLeave);
            } else {
              performLeave();
            }
          }
        } else {
          hostInsert(el, container, anchor);
        }
      };
      const unmount2 = (vnode, parentComponent, parentSuspense, doRemove = false, optimized = false) => {
        const {
          type,
          props,
          ref: ref3,
          children,
          dynamicChildren,
          shapeFlag,
          patchFlag,
          dirs,
          cacheIndex,
          memo
        } = vnode;
        if (patchFlag === -2 || dynamicChildren && dynamicChildren.hasOnce) {
          optimized = false;
        }
        if (ref3 != null) {
          pauseTracking();
          setRef(ref3, null, parentSuspense, vnode, true);
          resetTracking();
        }
        if (cacheIndex != null && (!vnode.ctx || vnode.ctx === parentComponent)) {
          parentComponent.renderCache[cacheIndex] = void 0;
        }
        if (shapeFlag & 256) {
          parentComponent.ctx.deactivate(vnode);
          return;
        }
        const shouldInvokeDirs = shapeFlag & 1 && dirs;
        const shouldInvokeVnodeHook = !isAsyncWrapper(vnode);
        let vnodeHook;
        if (shouldInvokeVnodeHook && (vnodeHook = props && props.onVnodeBeforeUnmount)) {
          invokeVNodeHook(vnodeHook, parentComponent, vnode);
        }
        if (shapeFlag & 6) {
          unmountComponent(vnode.component, parentSuspense, doRemove);
        } else {
          if (shapeFlag & 128) {
            vnode.suspense.unmount(parentSuspense, doRemove);
            return;
          }
          if (shouldInvokeDirs) {
            invokeDirectiveHook(vnode, null, parentComponent, "beforeUnmount");
          }
          if (shapeFlag & 64) {
            vnode.type.remove(
              vnode,
              parentComponent,
              parentSuspense,
              internals,
              doRemove
            );
          } else if (dynamicChildren && // #5154
          // when v-once is used inside a block, setBlockTracking(-1) marks the
          // parent block with hasOnce: true
          // so that it doesn't take the fast path during unmount - otherwise
          // components nested in v-once are never unmounted.
          !dynamicChildren.hasOnce && // #1153: fast path should not be taken for non-stable (v-for) fragments
          (type !== Fragment || patchFlag > 0 && patchFlag & 64)) {
            unmountChildren(
              dynamicChildren,
              parentComponent,
              parentSuspense,
              false,
              true
            );
          } else if (type === Fragment && patchFlag & (128 | 256) || !optimized && shapeFlag & 16) {
            unmountChildren(children, parentComponent, parentSuspense);
          }
          if (doRemove) {
            remove2(vnode);
          }
        }
        const shouldInvalidateMemo = memo != null && cacheIndex == null;
        if (shouldInvokeVnodeHook && (vnodeHook = props && props.onVnodeUnmounted) || shouldInvokeDirs || shouldInvalidateMemo) {
          queuePostRenderEffect(() => {
            vnodeHook && invokeVNodeHook(vnodeHook, parentComponent, vnode);
            shouldInvokeDirs && invokeDirectiveHook(vnode, null, parentComponent, "unmounted");
            if (shouldInvalidateMemo) {
              vnode.el = null;
            }
          }, parentSuspense);
        }
      };
      const remove2 = (vnode) => {
        const { type, el, anchor, transition } = vnode;
        if (type === Fragment) {
          {
            removeFragment(el, anchor);
          }
          return;
        }
        if (type === Static) {
          removeStaticNode(vnode);
          if (transition && !transition.persisted && transition.afterLeave) {
            transition.afterLeave();
          }
          return;
        }
        const performRemove = () => {
          hostRemove(el);
          if (transition && !transition.persisted && transition.afterLeave) {
            transition.afterLeave();
          }
        };
        if (vnode.shapeFlag & 1 && transition && !transition.persisted) {
          const { leave, delayLeave } = transition;
          const performLeave = () => leave(el, performRemove);
          if (delayLeave) {
            delayLeave(vnode.el, performRemove, performLeave);
          } else {
            performLeave();
          }
        } else {
          performRemove();
        }
      };
      const removeFragment = (cur, end) => {
        let next;
        while (cur !== end) {
          next = hostNextSibling(cur);
          hostRemove(cur);
          cur = next;
        }
        hostRemove(end);
      };
      const unmountComponent = (instance, parentSuspense, doRemove) => {
        const { bum, scope, job, subTree, um, m, a } = instance;
        invalidateMount(m);
        invalidateMount(a);
        if (bum) {
          invokeArrayFns(bum);
        }
        scope.stop();
        if (job) {
          job.flags |= 8;
          unmount2(subTree, instance, parentSuspense, doRemove);
        } else if (instance.vnode.el && subTree) {
          subTree.transition = instance.vnode.transition;
          unmount2(subTree, instance, parentSuspense, doRemove);
        }
        if (um) {
          queuePostRenderEffect(um, parentSuspense);
        }
        queuePostRenderEffect(() => {
          instance.isUnmounted = true;
        }, parentSuspense);
      };
      const unmountChildren = (children, parentComponent, parentSuspense, doRemove = false, optimized = false, start = 0) => {
        for (let i = start; i < children.length; i++) {
          unmount2(children[i], parentComponent, parentSuspense, doRemove, optimized);
        }
      };
      const getNextHostNode = (vnode) => {
        if (vnode.shapeFlag & 6) {
          return getNextHostNode(vnode.component.subTree);
        }
        if (vnode.shapeFlag & 128) {
          return vnode.suspense.next();
        }
        const el = hostNextSibling(vnode.anchor || vnode.el);
        const teleportEnd = el && el[TeleportEndKey];
        return teleportEnd ? hostNextSibling(teleportEnd) : el;
      };
      let isFlushing = false;
      const render2 = (vnode, container, namespace) => {
        let instance;
        if (vnode == null) {
          if (container._vnode) {
            unmount2(container._vnode, null, null, true);
            instance = container._vnode.component;
          }
        } else {
          patch(
            container._vnode || null,
            vnode,
            container,
            null,
            null,
            null,
            namespace
          );
        }
        container._vnode = vnode;
        if (!isFlushing) {
          isFlushing = true;
          flushPreFlushCbs(instance);
          flushPostFlushCbs();
          isFlushing = false;
        }
      };
      const internals = {
        p: patch,
        um: unmount2,
        m: move,
        r: remove2,
        mt: mountComponent,
        mc: mountChildren,
        pc: patchChildren,
        pbc: patchBlockChildren,
        n: getNextHostNode,
        o: options
      };
      let hydrate;
      return {
        render: render2,
        hydrate,
        createApp: createAppAPI(render2)
      };
    }
    function resolveChildrenNamespace({ type, props }, currentNamespace) {
      return currentNamespace === "svg" && type === "foreignObject" || currentNamespace === "mathml" && type === "annotation-xml" && props && props.encoding && props.encoding.includes("html") ? void 0 : currentNamespace;
    }
    function toggleRecurse({ effect: effect2, job }, allowed) {
      if (allowed) {
        effect2.flags |= 32;
        job.flags |= 4;
      } else {
        effect2.flags &= -33;
        job.flags &= -5;
      }
    }
    function needTransition(parentSuspense, transition) {
      return (!parentSuspense || parentSuspense && !parentSuspense.pendingBranch) && transition && !transition.persisted;
    }
    function traverseStaticChildren(n1, n2, shallow = false) {
      const ch1 = n1.children;
      const ch2 = n2.children;
      if (isArray$1(ch1) && isArray$1(ch2)) {
        for (let i = 0; i < ch1.length; i++) {
          const c1 = ch1[i];
          let c2 = ch2[i];
          if (c2.shapeFlag & 1 && !c2.dynamicChildren) {
            if (c2.patchFlag <= 0 || c2.patchFlag === 32) {
              c2 = ch2[i] = cloneIfMounted$1(ch2[i]);
              c2.el = c1.el;
            }
            if (!shallow && c2.patchFlag !== -2)
              traverseStaticChildren(c1, c2);
          }
          if (c2.type === Text) {
            if (c2.patchFlag === -1) {
              c2 = ch2[i] = cloneIfMounted$1(c2);
            }
            c2.el = c1.el;
          }
          if (c2.type === Comment && !c2.el) {
            c2.el = c1.el;
          }
        }
      }
    }
    function getSequence(arr) {
      const p2 = arr.slice();
      const result = [0];
      let i, j, u, v, c2;
      const len = arr.length;
      for (i = 0; i < len; i++) {
        const arrI = arr[i];
        if (arrI !== 0) {
          j = result[result.length - 1];
          if (arr[j] < arrI) {
            p2[i] = j;
            result.push(i);
            continue;
          }
          u = 0;
          v = result.length - 1;
          while (u < v) {
            c2 = u + v >> 1;
            if (arr[result[c2]] < arrI) {
              u = c2 + 1;
            } else {
              v = c2;
            }
          }
          if (arrI < arr[result[u]]) {
            if (u > 0) {
              p2[i] = result[u - 1];
            }
            result[u] = i;
          }
        }
      }
      u = result.length;
      v = result[u - 1];
      while (u-- > 0) {
        result[u] = v;
        v = p2[v];
      }
      return result;
    }
    function locateNonHydratedAsyncRoot(instance) {
      const subComponent = instance.subTree.component;
      if (subComponent) {
        if (subComponent.asyncDep && !subComponent.asyncResolved) {
          return subComponent;
        } else {
          return locateNonHydratedAsyncRoot(subComponent);
        }
      }
    }
    function invalidateMount(hooks) {
      if (hooks) {
        for (let i = 0; i < hooks.length; i++)
          hooks[i].flags |= 8;
      }
    }
    function resolveAsyncComponentPlaceholder(anchorVnode) {
      if (anchorVnode.placeholder) {
        return anchorVnode.placeholder;
      }
      const instance = anchorVnode.component;
      if (instance) {
        return resolveAsyncComponentPlaceholder(instance.subTree);
      }
      return null;
    }
    const isSuspense = (type) => type.__isSuspense;
    function queueEffectWithSuspense(fn, suspense) {
      if (suspense && suspense.pendingBranch) {
        if (isArray$1(fn)) {
          suspense.effects.push(...fn);
        } else {
          suspense.effects.push(fn);
        }
      } else {
        queuePostFlushCb(fn);
      }
    }
    const Fragment = /* @__PURE__ */ Symbol.for("v-fgt");
    const Text = /* @__PURE__ */ Symbol.for("v-txt");
    const Comment = /* @__PURE__ */ Symbol.for("v-cmt");
    const Static = /* @__PURE__ */ Symbol.for("v-stc");
    const blockStack = [];
    let currentBlock = null;
    function openBlock(disableTracking = false) {
      blockStack.push(currentBlock = disableTracking ? null : []);
    }
    function closeBlock() {
      blockStack.pop();
      currentBlock = blockStack[blockStack.length - 1] || null;
    }
    let isBlockTreeEnabled = 1;
    function setBlockTracking(value, inVOnce = false) {
      isBlockTreeEnabled += value;
      if (value < 0 && currentBlock && inVOnce) {
        currentBlock.hasOnce = true;
      }
    }
    function setupBlock(vnode) {
      vnode.dynamicChildren = isBlockTreeEnabled > 0 ? currentBlock || EMPTY_ARR : null;
      closeBlock();
      if (isBlockTreeEnabled > 0 && currentBlock) {
        currentBlock.push(vnode);
      }
      return vnode;
    }
    function createElementBlock(type, props, children, patchFlag, dynamicProps, shapeFlag) {
      return setupBlock(
        createBaseVNode(
          type,
          props,
          children,
          patchFlag,
          dynamicProps,
          shapeFlag,
          true
        )
      );
    }
    function createBlock(type, props, children, patchFlag, dynamicProps) {
      return setupBlock(
        createVNode(
          type,
          props,
          children,
          patchFlag,
          dynamicProps,
          true
        )
      );
    }
    function isVNode(value) {
      return value ? value.__v_isVNode === true : false;
    }
    function isSameVNodeType(n1, n2) {
      return n1.type === n2.type && n1.key === n2.key;
    }
    const normalizeKey = ({ key }) => key != null ? key : null;
    const normalizeRef = ({
      ref: ref3,
      ref_key,
      ref_for
    }) => {
      if (typeof ref3 === "number") {
        ref3 = "" + ref3;
      }
      return ref3 != null ? isString(ref3) || /* @__PURE__ */ isRef(ref3) || isFunction$1(ref3) ? { i: currentRenderingInstance, r: ref3, k: ref_key, f: !!ref_for } : ref3 : null;
    };
    function createBaseVNode(type, props = null, children = null, patchFlag = 0, dynamicProps = null, shapeFlag = type === Fragment ? 0 : 1, isBlockNode = false, needFullChildrenNormalization = false) {
      const vnode = {
        __v_isVNode: true,
        __v_skip: true,
        type,
        props,
        key: props && normalizeKey(props),
        ref: props && normalizeRef(props),
        scopeId: currentScopeId,
        slotScopeIds: null,
        children,
        component: null,
        suspense: null,
        ssContent: null,
        ssFallback: null,
        dirs: null,
        transition: null,
        el: null,
        anchor: null,
        target: null,
        targetStart: null,
        targetAnchor: null,
        staticCount: 0,
        shapeFlag,
        patchFlag,
        dynamicProps,
        dynamicChildren: null,
        appContext: null,
        ctx: currentRenderingInstance
      };
      if (needFullChildrenNormalization) {
        normalizeChildren(vnode, children);
        if (shapeFlag & 128) {
          type.normalize(vnode);
        }
      } else if (children) {
        vnode.shapeFlag |= isString(children) ? 8 : 16;
      }
      if (isBlockTreeEnabled > 0 && // avoid a block node from tracking itself
      !isBlockNode && // has current parent block
      currentBlock && // presence of a patch flag indicates this node needs patching on updates.
      // component nodes also should always be patched, because even if the
      // component doesn't need to update, it needs to persist the instance on to
      // the next vnode so that it can be properly unmounted later.
      (vnode.patchFlag > 0 || shapeFlag & 6) && // the EVENTS flag is only for hydration and if it is the only flag, the
      // vnode should not be considered dynamic due to handler caching.
      vnode.patchFlag !== 32) {
        currentBlock.push(vnode);
      }
      return vnode;
    }
    const createVNode = _createVNode;
    function _createVNode(type, props = null, children = null, patchFlag = 0, dynamicProps = null, isBlockNode = false) {
      if (!type || type === NULL_DYNAMIC_COMPONENT) {
        type = Comment;
      }
      if (isVNode(type)) {
        const cloned = cloneVNode(
          type,
          props,
          true
          /* mergeRef: true */
        );
        if (children) {
          normalizeChildren(cloned, children);
        }
        if (isBlockTreeEnabled > 0 && !isBlockNode && currentBlock) {
          if (cloned.shapeFlag & 6) {
            currentBlock[currentBlock.indexOf(type)] = cloned;
          } else {
            currentBlock.push(cloned);
          }
        }
        cloned.patchFlag = -2;
        return cloned;
      }
      if (isClassComponent(type)) {
        type = type.__vccOpts;
      }
      if (props) {
        props = guardReactiveProps(props);
        let { class: klass, style } = props;
        if (klass && !isString(klass)) {
          props.class = normalizeClass(klass);
        }
        if (isObject$1(style)) {
          if (/* @__PURE__ */ isProxy(style) && !isArray$1(style)) {
            style = extend({}, style);
          }
          props.style = normalizeStyle(style);
        }
      }
      const shapeFlag = isString(type) ? 1 : isSuspense(type) ? 128 : isTeleport(type) ? 64 : isObject$1(type) ? 4 : isFunction$1(type) ? 2 : 0;
      return createBaseVNode(
        type,
        props,
        children,
        patchFlag,
        dynamicProps,
        shapeFlag,
        isBlockNode,
        true
      );
    }
    function guardReactiveProps(props) {
      if (!props) return null;
      return /* @__PURE__ */ isProxy(props) || isInternalObject(props) ? extend({}, props) : props;
    }
    function cloneVNode(vnode, extraProps, mergeRef = false, cloneTransition = false) {
      const { props, ref: ref3, patchFlag, children, transition } = vnode;
      const mergedProps = extraProps ? mergeProps(props || {}, extraProps) : props;
      const cloned = {
        __v_isVNode: true,
        __v_skip: true,
        type: vnode.type,
        props: mergedProps,
        key: mergedProps && normalizeKey(mergedProps),
        ref: extraProps && extraProps.ref ? (
          // #2078 in the case of <component :is="vnode" ref="extra"/>
          // if the vnode itself already has a ref, cloneVNode will need to merge
          // the refs so the single vnode can be set on multiple refs
          mergeRef && ref3 ? isArray$1(ref3) ? ref3.concat(normalizeRef(extraProps)) : [ref3, normalizeRef(extraProps)] : normalizeRef(extraProps)
        ) : ref3,
        scopeId: vnode.scopeId,
        slotScopeIds: vnode.slotScopeIds,
        children,
        target: vnode.target,
        targetStart: vnode.targetStart,
        targetAnchor: vnode.targetAnchor,
        staticCount: vnode.staticCount,
        shapeFlag: vnode.shapeFlag,
        // if the vnode is cloned with extra props, we can no longer assume its
        // existing patch flag to be reliable and need to add the FULL_PROPS flag.
        // note: preserve flag for fragments since they use the flag for children
        // fast paths only.
        patchFlag: extraProps && vnode.type !== Fragment ? patchFlag === -1 ? 16 : patchFlag | 16 : patchFlag,
        dynamicProps: vnode.dynamicProps,
        dynamicChildren: vnode.dynamicChildren,
        appContext: vnode.appContext,
        dirs: vnode.dirs,
        transition,
        // These should technically only be non-null on mounted VNodes. However,
        // they *should* be copied for kept-alive vnodes. So we just always copy
        // them since them being non-null during a mount doesn't affect the logic as
        // they will simply be overwritten.
        component: vnode.component,
        suspense: vnode.suspense,
        ssContent: vnode.ssContent && cloneVNode(vnode.ssContent),
        ssFallback: vnode.ssFallback && cloneVNode(vnode.ssFallback),
        placeholder: vnode.placeholder,
        el: vnode.el,
        anchor: vnode.anchor,
        ctx: vnode.ctx,
        ce: vnode.ce,
        cacheIndex: vnode.cacheIndex
      };
      if (transition && cloneTransition) {
        setTransitionHooks(
          cloned,
          transition.clone(cloned)
        );
      }
      return cloned;
    }
    function createTextVNode(text = " ", flag = 0) {
      return createVNode(Text, null, text, flag);
    }
    function createStaticVNode(content, numberOfNodes) {
      const vnode = createVNode(Static, null, content);
      vnode.staticCount = numberOfNodes;
      return vnode;
    }
    function createCommentVNode(text = "", asBlock = false) {
      return asBlock ? (openBlock(), createBlock(Comment, null, text)) : createVNode(Comment, null, text);
    }
    function normalizeVNode$1(child) {
      if (child == null || typeof child === "boolean") {
        return createVNode(Comment);
      } else if (isArray$1(child)) {
        return createVNode(
          Fragment,
          null,
          // #3666, avoid reference pollution when reusing vnode
          child.slice()
        );
      } else if (isVNode(child)) {
        return cloneIfMounted$1(child);
      } else {
        return createVNode(Text, null, String(child));
      }
    }
    function cloneIfMounted$1(child) {
      return child.el === null && child.patchFlag !== -1 || child.memo ? child : cloneVNode(child);
    }
    function normalizeChildren(vnode, children) {
      let type = 0;
      const { shapeFlag } = vnode;
      if (children == null) {
        children = null;
      } else if (isArray$1(children)) {
        type = 16;
      } else if (typeof children === "object") {
        if (shapeFlag & (1 | 64)) {
          const slot = children.default;
          if (slot) {
            slot._c && (slot._d = false);
            normalizeChildren(vnode, slot());
            slot._c && (slot._d = true);
          }
          return;
        } else {
          type = 32;
          const slotFlag = children._;
          if (!slotFlag && !isInternalObject(children)) {
            children._ctx = currentRenderingInstance;
          } else if (slotFlag === 3 && currentRenderingInstance) {
            if (currentRenderingInstance.slots._ === 1) {
              children._ = 1;
            } else {
              children._ = 2;
              vnode.patchFlag |= 1024;
            }
          }
        }
      } else if (isFunction$1(children)) {
        if (shapeFlag & (1 | 64)) {
          normalizeChildren(vnode, { default: children });
          return;
        }
        children = { default: children, _ctx: currentRenderingInstance };
        type = 32;
      } else {
        children = String(children);
        if (shapeFlag & 64) {
          type = 16;
          children = [createTextVNode(children)];
        } else {
          type = 8;
        }
      }
      vnode.children = children;
      vnode.shapeFlag |= type;
    }
    function mergeProps(...args) {
      const ret = {};
      for (let i = 0; i < args.length; i++) {
        const toMerge = args[i];
        for (const key in toMerge) {
          if (key === "class") {
            if (ret.class !== toMerge.class) {
              ret.class = normalizeClass([ret.class, toMerge.class]);
            }
          } else if (key === "style") {
            ret.style = normalizeStyle([ret.style, toMerge.style]);
          } else if (isOn(key)) {
            const existing = ret[key];
            const incoming = toMerge[key];
            if (incoming && existing !== incoming && !(isArray$1(existing) && existing.includes(incoming))) {
              ret[key] = existing ? [].concat(existing, incoming) : incoming;
            } else if (incoming == null && existing == null && // mergeProps({ 'onUpdate:modelValue': undefined }) should not retain
            // the model listener.
            !isModelListener(key)) {
              ret[key] = incoming;
            }
          } else if (key !== "") {
            ret[key] = toMerge[key];
          }
        }
      }
      return ret;
    }
    function invokeVNodeHook(hook, instance, vnode, prevVNode = null) {
      callWithAsyncErrorHandling(hook, instance, 7, [
        vnode,
        prevVNode
      ]);
    }
    const emptyAppContext = createAppContext();
    let uid = 0;
    function createComponentInstance(vnode, parent, suspense) {
      const type = vnode.type;
      const appContext = (parent ? parent.appContext : vnode.appContext) || emptyAppContext;
      const instance = {
        uid: uid++,
        vnode,
        type,
        parent,
        appContext,
        root: null,
        // to be immediately set
        next: null,
        subTree: null,
        // will be set synchronously right after creation
        effect: null,
        update: null,
        // will be set synchronously right after creation
        job: null,
        scope: new EffectScope(
          true
          /* detached */
        ),
        render: null,
        proxy: null,
        exposed: null,
        exposeProxy: null,
        withProxy: null,
        provides: parent ? parent.provides : Object.create(appContext.provides),
        ids: parent ? parent.ids : ["", 0, 0],
        accessCache: null,
        renderCache: [],
        // local resolved assets
        components: null,
        directives: null,
        // resolved props and emits options
        propsOptions: normalizePropsOptions(type, appContext),
        emitsOptions: normalizeEmitsOptions(type, appContext),
        // emit
        emit: null,
        // to be set immediately
        emitted: null,
        // props default value
        propsDefaults: EMPTY_OBJ,
        // inheritAttrs
        inheritAttrs: type.inheritAttrs,
        // state
        ctx: EMPTY_OBJ,
        data: EMPTY_OBJ,
        props: EMPTY_OBJ,
        attrs: EMPTY_OBJ,
        slots: EMPTY_OBJ,
        refs: EMPTY_OBJ,
        setupState: EMPTY_OBJ,
        setupContext: null,
        // suspense related
        suspense,
        suspenseId: suspense ? suspense.pendingId : 0,
        asyncDep: null,
        asyncResolved: false,
        // lifecycle hooks
        // not using enums here because it results in computed properties
        isMounted: false,
        isUnmounted: false,
        isDeactivated: false,
        bc: null,
        c: null,
        bm: null,
        m: null,
        bu: null,
        u: null,
        um: null,
        bum: null,
        da: null,
        a: null,
        rtg: null,
        rtc: null,
        ec: null,
        sp: null
      };
      {
        instance.ctx = { _: instance };
      }
      instance.root = parent ? parent.root : instance;
      instance.emit = emit.bind(null, instance);
      if (vnode.ce) {
        vnode.ce(instance);
      }
      return instance;
    }
    let currentInstance = null;
    const getCurrentInstance = () => currentInstance || currentRenderingInstance;
    let internalSetCurrentInstance;
    let setInSSRSetupState;
    {
      const g = getGlobalThis();
      const registerGlobalSetter = (key, setter) => {
        let setters;
        if (!(setters = g[key])) setters = g[key] = [];
        setters.push(setter);
        return (v) => {
          if (setters.length > 1) setters.forEach((set) => set(v));
          else setters[0](v);
        };
      };
      internalSetCurrentInstance = registerGlobalSetter(
        `__VUE_INSTANCE_SETTERS__`,
        (v) => currentInstance = v
      );
      setInSSRSetupState = registerGlobalSetter(
        `__VUE_SSR_SETTERS__`,
        (v) => isInSSRComponentSetup = v
      );
    }
    const setCurrentInstance = (instance) => {
      const prev = currentInstance;
      internalSetCurrentInstance(instance);
      instance.scope.on();
      return () => {
        instance.scope.off();
        internalSetCurrentInstance(prev);
      };
    };
    const unsetCurrentInstance = () => {
      currentInstance && currentInstance.scope.off();
      internalSetCurrentInstance(null);
    };
    function isStatefulComponent(instance) {
      return instance.vnode.shapeFlag & 4;
    }
    let isInSSRComponentSetup = false;
    function setupComponent(instance, isSSR = false, optimized = false) {
      isSSR && setInSSRSetupState(isSSR);
      const { props, children } = instance.vnode;
      const isStateful = isStatefulComponent(instance);
      initProps(instance, props, isStateful, isSSR);
      initSlots(instance, children, optimized || isSSR);
      const setupResult = isStateful ? setupStatefulComponent(instance, isSSR) : void 0;
      isSSR && setInSSRSetupState(false);
      return setupResult;
    }
    function setupStatefulComponent(instance, isSSR) {
      const Component = instance.type;
      instance.accessCache = /* @__PURE__ */ Object.create(null);
      instance.proxy = new Proxy(instance.ctx, PublicInstanceProxyHandlers);
      const { setup } = Component;
      if (setup) {
        pauseTracking();
        const setupContext = instance.setupContext = setup.length > 1 ? createSetupContext(instance) : null;
        const reset = setCurrentInstance(instance);
        const setupResult = callWithErrorHandling(
          setup,
          instance,
          0,
          [
            instance.props,
            setupContext
          ]
        );
        const isAsyncSetup = isPromise(setupResult);
        resetTracking();
        reset();
        if ((isAsyncSetup || instance.sp) && !isAsyncWrapper(instance)) {
          markAsyncBoundary(instance);
        }
        if (isAsyncSetup) {
          setupResult.then(unsetCurrentInstance, unsetCurrentInstance);
          if (isSSR) {
            return setupResult.then((resolvedResult) => {
              setInSSRSetupState(true);
              try {
                handleSetupResult(instance, resolvedResult, isSSR);
              } finally {
                setInSSRSetupState(false);
              }
            }).catch((e) => {
              handleError(e, instance, 0);
            });
          } else {
            instance.asyncDep = setupResult;
          }
        } else {
          handleSetupResult(instance, setupResult);
        }
      } else {
        finishComponentSetup(instance);
      }
    }
    function handleSetupResult(instance, setupResult, isSSR) {
      if (isFunction$1(setupResult)) {
        if (instance.type.__ssrInlineRender) {
          instance.ssrRender = setupResult;
        } else {
          instance.render = setupResult;
        }
      } else if (isObject$1(setupResult)) {
        instance.setupState = proxyRefs(setupResult);
      } else ;
      finishComponentSetup(instance);
    }
    function finishComponentSetup(instance, isSSR, skipOptions) {
      const Component = instance.type;
      if (!instance.render) {
        instance.render = Component.render || NOOP;
      }
      {
        const reset = setCurrentInstance(instance);
        pauseTracking();
        try {
          applyOptions(instance);
        } finally {
          resetTracking();
          reset();
        }
      }
    }
    const attrsProxyHandlers = {
      get(target, key) {
        track(target, "get", "");
        return target[key];
      }
    };
    function createSetupContext(instance) {
      const expose = (exposed) => {
        instance.exposed = exposed || {};
      };
      {
        return {
          attrs: new Proxy(instance.attrs, attrsProxyHandlers),
          slots: instance.slots,
          emit: instance.emit,
          expose
        };
      }
    }
    function getComponentPublicInstance(instance) {
      if (instance.exposed) {
        return instance.exposeProxy || (instance.exposeProxy = new Proxy(proxyRefs(markRaw(instance.exposed)), {
          get(target, key) {
            if (key in target) {
              return target[key];
            } else if (key in publicPropertiesMap) {
              return publicPropertiesMap[key](instance);
            }
          },
          has(target, key) {
            return key in target || key in publicPropertiesMap;
          }
        }));
      } else {
        return instance.proxy;
      }
    }
    const classifyRE = /(?:^|[-_])\w/g;
    const classify = (str) => str.replace(classifyRE, (c2) => c2.toUpperCase()).replace(/[-_]/g, "");
    function getComponentName(Component, includeInferred = true) {
      return isFunction$1(Component) ? Component.displayName || Component.name : Component.name || includeInferred && Component.__name;
    }
    function formatComponentName(instance, Component, isRoot = false) {
      let name = getComponentName(Component);
      if (!name && Component.__file) {
        const match = Component.__file.match(/([^/\\]+)\.\w+$/);
        if (match) {
          name = match[1];
        }
      }
      if (!name && instance) {
        const inferFromRegistry = (registry) => {
          for (const key in registry) {
            if (registry[key] === Component) {
              return key;
            }
          }
        };
        name = inferFromRegistry(instance.components) || instance.parent && inferFromRegistry(
          instance.parent.type.components
        ) || inferFromRegistry(instance.appContext.components);
      }
      return name ? classify(name) : isRoot ? `App` : `Anonymous`;
    }
    function isClassComponent(value) {
      return isFunction$1(value) && "__vccOpts" in value;
    }
    const computed = (getterOrOptions, debugOptions) => {
      const c2 = /* @__PURE__ */ computed$1(getterOrOptions, debugOptions, isInSSRComponentSetup);
      return c2;
    };
    function h(type, propsOrChildren, children) {
      try {
        setBlockTracking(-1);
        const l = arguments.length;
        if (l === 2) {
          if (isObject$1(propsOrChildren) && !isArray$1(propsOrChildren)) {
            if (isVNode(propsOrChildren)) {
              return createVNode(type, null, [propsOrChildren]);
            }
            return createVNode(type, propsOrChildren);
          } else {
            return createVNode(type, null, propsOrChildren);
          }
        } else {
          if (l > 3) {
            children = Array.prototype.slice.call(arguments, 2);
          } else if (l === 3 && isVNode(children)) {
            children = [children];
          }
          return createVNode(type, propsOrChildren, children);
        }
      } finally {
        setBlockTracking(1);
      }
    }
    const version = "3.5.43";
    /**
    * @vue/runtime-dom v3.5.43
    * (c) 2018-present Yuxi (Evan) You and Vue contributors
    * @license MIT
    **/
    let policy = void 0;
    const tt = typeof window !== "undefined" && window.trustedTypes;
    if (tt) {
      try {
        policy = /* @__PURE__ */ tt.createPolicy("vue", {
          createHTML: (val) => val
        });
      } catch (e) {
      }
    }
    const unsafeToTrustedHTML = policy ? (val) => policy.createHTML(val) : (val) => val;
    const svgNS = "http://www.w3.org/2000/svg";
    const mathmlNS = "http://www.w3.org/1998/Math/MathML";
    const doc = typeof document !== "undefined" ? document : null;
    const templateContainer = doc && /* @__PURE__ */ doc.createElement("template");
    const nodeOps = {
      insert: (child, parent, anchor) => {
        parent.insertBefore(child, anchor || null);
      },
      remove: (child) => {
        const parent = child.parentNode;
        if (parent) {
          parent.removeChild(child);
        }
      },
      createElement: (tag, namespace, is, props) => {
        const el = namespace === "svg" ? doc.createElementNS(svgNS, tag) : namespace === "mathml" ? doc.createElementNS(mathmlNS, tag) : is ? doc.createElement(tag, { is }) : doc.createElement(tag);
        if (tag === "select" && props && props.multiple != null) {
          el.setAttribute("multiple", props.multiple);
        }
        return el;
      },
      createText: (text) => doc.createTextNode(text),
      createComment: (text) => doc.createComment(text),
      setText: (node, text) => {
        node.nodeValue = text;
      },
      setElementText: (el, text) => {
        el.textContent = text;
      },
      parentNode: (node) => node.parentNode,
      nextSibling: (node) => node.nextSibling,
      querySelector: (selector) => doc.querySelector(selector),
      setScopeId(el, id) {
        el.setAttribute(id, "");
      },
      // __UNSAFE__
      // Reason: innerHTML.
      // Static content here can only come from compiled templates.
      // As long as the user only uses trusted templates, this is safe.
      insertStaticContent(content, parent, anchor, namespace, start, end) {
        const before = anchor ? anchor.previousSibling : parent.lastChild;
        if (start && (start === end || start.nextSibling)) {
          while (true) {
            parent.insertBefore(start.cloneNode(true), anchor);
            if (start === end || !(start = start.nextSibling)) break;
          }
        } else {
          templateContainer.innerHTML = unsafeToTrustedHTML(
            namespace === "svg" ? `<svg>${content}</svg>` : namespace === "mathml" ? `<math>${content}</math>` : content
          );
          const template = templateContainer.content;
          if (namespace === "svg" || namespace === "mathml") {
            const wrapper = template.firstChild;
            while (wrapper.firstChild) {
              template.appendChild(wrapper.firstChild);
            }
            template.removeChild(wrapper);
          }
          parent.insertBefore(template, anchor);
        }
        return [
          // first
          before ? before.nextSibling : parent.firstChild,
          // last
          anchor ? anchor.previousSibling : parent.lastChild
        ];
      }
    };
    const TRANSITION = "transition";
    const ANIMATION = "animation";
    const vtcKey = /* @__PURE__ */ Symbol("_vtc");
    const DOMTransitionPropsValidators = {
      name: String,
      type: String,
      css: {
        type: Boolean,
        default: true
      },
      duration: [String, Number, Object],
      enterFromClass: String,
      enterActiveClass: String,
      enterToClass: String,
      appearFromClass: String,
      appearActiveClass: String,
      appearToClass: String,
      leaveFromClass: String,
      leaveActiveClass: String,
      leaveToClass: String
    };
    const TransitionPropsValidators = /* @__PURE__ */ extend(
      {},
      BaseTransitionPropsValidators,
      DOMTransitionPropsValidators
    );
    const decorate$1 = (t) => {
      t.displayName = "Transition";
      t.props = TransitionPropsValidators;
      return t;
    };
    const Transition = /* @__PURE__ */ decorate$1(
      (props, { slots }) => h(BaseTransition, resolveTransitionProps(props), slots)
    );
    const callHook = (hook, args = []) => {
      if (isArray$1(hook)) {
        hook.forEach((h2) => h2(...args));
      } else if (hook) {
        hook(...args);
      }
    };
    const hasExplicitCallback = (hook) => {
      return hook ? isArray$1(hook) ? hook.some((h2) => h2.length > 1) : hook.length > 1 : false;
    };
    function resolveTransitionProps(rawProps) {
      const baseProps = {};
      for (const key in rawProps) {
        if (!(key in DOMTransitionPropsValidators)) {
          baseProps[key] = rawProps[key];
        }
      }
      if (rawProps.css === false) {
        return baseProps;
      }
      const {
        name = "v",
        type,
        duration: duration2,
        enterFromClass = `${name}-enter-from`,
        enterActiveClass = `${name}-enter-active`,
        enterToClass = `${name}-enter-to`,
        appearFromClass = enterFromClass,
        appearActiveClass = enterActiveClass,
        appearToClass = enterToClass,
        leaveFromClass = `${name}-leave-from`,
        leaveActiveClass = `${name}-leave-active`,
        leaveToClass = `${name}-leave-to`
      } = rawProps;
      const durations = normalizeDuration(duration2);
      const enterDuration = durations && durations[0];
      const leaveDuration = durations && durations[1];
      const {
        onBeforeEnter,
        onEnter,
        onEnterCancelled,
        onLeave,
        onLeaveCancelled,
        onBeforeAppear = onBeforeEnter,
        onAppear = onEnter,
        onAppearCancelled = onEnterCancelled
      } = baseProps;
      const finishEnter = (el, isAppear, done, isCancelled) => {
        el._enterCancelled = isCancelled;
        removeTransitionClass(el, isAppear ? appearToClass : enterToClass);
        removeTransitionClass(el, isAppear ? appearActiveClass : enterActiveClass);
        done && done();
      };
      const finishLeave = (el, done) => {
        el._isLeaving = false;
        removeTransitionClass(el, leaveFromClass);
        removeTransitionClass(el, leaveToClass);
        removeTransitionClass(el, leaveActiveClass);
        done && done();
      };
      const makeEnterHook = (isAppear) => {
        return (el, done) => {
          const hook = isAppear ? onAppear : onEnter;
          const resolve2 = () => finishEnter(el, isAppear, done);
          callHook(hook, [el, resolve2]);
          nextFrame(() => {
            removeTransitionClass(el, isAppear ? appearFromClass : enterFromClass);
            addTransitionClass(el, isAppear ? appearToClass : enterToClass);
            if (!hasExplicitCallback(hook)) {
              whenTransitionEnds(el, type, enterDuration, resolve2);
            }
          });
        };
      };
      return extend(baseProps, {
        onBeforeEnter(el) {
          callHook(onBeforeEnter, [el]);
          addTransitionClass(el, enterFromClass);
          addTransitionClass(el, enterActiveClass);
        },
        onBeforeAppear(el) {
          callHook(onBeforeAppear, [el]);
          addTransitionClass(el, appearFromClass);
          addTransitionClass(el, appearActiveClass);
        },
        onEnter: makeEnterHook(false),
        onAppear: makeEnterHook(true),
        onLeave(el, done) {
          el._isLeaving = true;
          const resolve2 = () => finishLeave(el, done);
          addTransitionClass(el, leaveFromClass);
          if (!el._enterCancelled) {
            forceReflow(el);
            addTransitionClass(el, leaveActiveClass);
          } else {
            addTransitionClass(el, leaveActiveClass);
            forceReflow(el);
          }
          nextFrame(() => {
            if (!el._isLeaving) {
              return;
            }
            removeTransitionClass(el, leaveFromClass);
            addTransitionClass(el, leaveToClass);
            if (!hasExplicitCallback(onLeave)) {
              whenTransitionEnds(el, type, leaveDuration, resolve2);
            }
          });
          callHook(onLeave, [el, resolve2]);
        },
        onEnterCancelled(el) {
          finishEnter(el, false, void 0, true);
          callHook(onEnterCancelled, [el]);
        },
        onAppearCancelled(el) {
          finishEnter(el, true, void 0, true);
          callHook(onAppearCancelled, [el]);
        },
        onLeaveCancelled(el) {
          finishLeave(el);
          callHook(onLeaveCancelled, [el]);
        }
      });
    }
    function normalizeDuration(duration2) {
      if (duration2 == null) {
        return null;
      } else if (isObject$1(duration2)) {
        return [NumberOf(duration2.enter), NumberOf(duration2.leave)];
      } else {
        const n = NumberOf(duration2);
        return [n, n];
      }
    }
    function NumberOf(val) {
      const res = toNumber(val);
      return res;
    }
    function addTransitionClass(el, cls) {
      cls.split(/\s+/).forEach((c2) => c2 && el.classList.add(c2));
      (el[vtcKey] || (el[vtcKey] = /* @__PURE__ */ new Set())).add(cls);
    }
    function removeTransitionClass(el, cls) {
      cls.split(/\s+/).forEach((c2) => c2 && el.classList.remove(c2));
      const _vtc = el[vtcKey];
      if (_vtc) {
        _vtc.delete(cls);
        if (!_vtc.size) {
          el[vtcKey] = void 0;
        }
      }
    }
    function nextFrame(cb) {
      requestAnimationFrame(() => {
        requestAnimationFrame(cb);
      });
    }
    let endId = 0;
    function whenTransitionEnds(el, expectedType, explicitTimeout, resolve2) {
      const id = el._endId = ++endId;
      const resolveIfNotStale = () => {
        if (id === el._endId) {
          resolve2();
        }
      };
      if (explicitTimeout != null) {
        return setTimeout(resolveIfNotStale, explicitTimeout);
      }
      const { type, timeout, propCount } = getTransitionInfo(el, expectedType);
      if (!type) {
        return resolve2();
      }
      const endEvent = type + "end";
      let ended = 0;
      const end = () => {
        el.removeEventListener(endEvent, onEnd);
        resolveIfNotStale();
      };
      const onEnd = (e) => {
        if (e.target === el && ++ended >= propCount) {
          end();
        }
      };
      setTimeout(() => {
        if (ended < propCount) {
          end();
        }
      }, timeout + 1);
      el.addEventListener(endEvent, onEnd);
    }
    function getTransitionInfo(el, expectedType) {
      const styles = window.getComputedStyle(el);
      const getStyleProperties = (key) => (styles[key] || "").split(", ");
      const transitionDelays = getStyleProperties(`${TRANSITION}Delay`);
      const transitionDurations = getStyleProperties(`${TRANSITION}Duration`);
      const transitionTimeout = getTimeout(transitionDelays, transitionDurations);
      const animationDelays = getStyleProperties(`${ANIMATION}Delay`);
      const animationDurations = getStyleProperties(`${ANIMATION}Duration`);
      const animationTimeout = getTimeout(animationDelays, animationDurations);
      let type = null;
      let timeout = 0;
      let propCount = 0;
      if (expectedType === TRANSITION) {
        if (transitionTimeout > 0) {
          type = TRANSITION;
          timeout = transitionTimeout;
          propCount = transitionDurations.length;
        }
      } else if (expectedType === ANIMATION) {
        if (animationTimeout > 0) {
          type = ANIMATION;
          timeout = animationTimeout;
          propCount = animationDurations.length;
        }
      } else {
        timeout = Math.max(transitionTimeout, animationTimeout);
        type = timeout > 0 ? transitionTimeout > animationTimeout ? TRANSITION : ANIMATION : null;
        propCount = type ? type === TRANSITION ? transitionDurations.length : animationDurations.length : 0;
      }
      const hasTransform = type === TRANSITION && /\b(?:transform|all)(?:,|$)/.test(
        getStyleProperties(`${TRANSITION}Property`).toString()
      );
      return {
        type,
        timeout,
        propCount,
        hasTransform
      };
    }
    function getTimeout(delays, durations) {
      while (delays.length < durations.length) {
        delays = delays.concat(delays);
      }
      return Math.max(...durations.map((d, i) => toMs(d) + toMs(delays[i])));
    }
    function toMs(s) {
      if (s === "auto") return 0;
      return Number(s.slice(0, -1).replace(",", ".")) * 1e3;
    }
    function forceReflow(el) {
      const targetDocument = el ? el.ownerDocument : document;
      return targetDocument.body.offsetHeight;
    }
    function patchClass(el, value, isSVG) {
      const transitionClasses = el[vtcKey];
      if (transitionClasses) {
        value = (value ? [value, ...transitionClasses] : [...transitionClasses]).join(" ");
      }
      if (value == null) {
        el.removeAttribute("class");
      } else if (isSVG) {
        el.setAttribute("class", value);
      } else {
        el.className = value;
      }
    }
    const vShowOriginalDisplay = /* @__PURE__ */ Symbol("_vod");
    const vShowHidden = /* @__PURE__ */ Symbol("_vsh");
    const CSS_VAR_TEXT = /* @__PURE__ */ Symbol("");
    const displayRE = /(?:^|;)\s*display\s*:/;
    function patchStyle(el, prev, next) {
      const style = el.style;
      const isCssString = isString(next);
      let hasControlledDisplay = false;
      if (next && !isCssString) {
        if (prev) {
          if (!isString(prev)) {
            for (const key in prev) {
              if (next[key] == null) {
                setStyle(style, key, "");
              }
            }
          } else {
            for (const prevStyle of prev.split(";")) {
              const key = prevStyle.slice(0, prevStyle.indexOf(":")).trim();
              if (next[key] == null) {
                setStyle(style, key, "");
              }
            }
          }
        }
        for (const key in next) {
          if (key === "display") {
            hasControlledDisplay = true;
          }
          const value = next[key];
          if (value != null) {
            if (!shouldPreserveTextareaResizeStyle(
              el,
              key,
              !isString(prev) && prev ? prev[key] : void 0,
              value
            )) {
              setStyle(style, key, value);
            }
          } else {
            setStyle(style, key, "");
          }
        }
      } else {
        if (isCssString) {
          if (prev !== next) {
            const cssVarText = style[CSS_VAR_TEXT];
            if (cssVarText) {
              next += ";" + cssVarText;
            }
            style.cssText = next;
            hasControlledDisplay = displayRE.test(next);
          }
        } else if (prev) {
          el.removeAttribute("style");
        }
      }
      if (vShowOriginalDisplay in el) {
        el[vShowOriginalDisplay] = hasControlledDisplay ? style.display : "";
        if (el[vShowHidden]) {
          style.display = "none";
        }
      }
    }
    const importantRE = /\s*!important$/;
    function setStyle(style, name, val) {
      if (isArray$1(val)) {
        val.forEach((v) => setStyle(style, name, v));
      } else {
        if (val == null) val = "";
        if (name.startsWith("--")) {
          if (importantRE.test(val)) {
            style.setProperty(name, val.replace(importantRE, ""), "important");
          } else {
            style.setProperty(name, val);
          }
        } else {
          const prefixed = autoPrefix(style, name);
          if (importantRE.test(val)) {
            style.setProperty(
              hyphenate(prefixed),
              val.replace(importantRE, ""),
              "important"
            );
          } else {
            style[prefixed] = val;
          }
        }
      }
    }
    const prefixes = ["Webkit", "Moz", "ms"];
    const prefixCache = {};
    function autoPrefix(style, rawName) {
      const cached = prefixCache[rawName];
      if (cached) {
        return cached;
      }
      let name = camelize(rawName);
      if (name !== "filter" && name in style) {
        return prefixCache[rawName] = name;
      }
      name = capitalize(name);
      for (let i = 0; i < prefixes.length; i++) {
        const prefixed = prefixes[i] + name;
        if (prefixed in style) {
          return prefixCache[rawName] = prefixed;
        }
      }
      return rawName;
    }
    function shouldPreserveTextareaResizeStyle(el, key, prev, next) {
      return el.tagName === "TEXTAREA" && (key === "width" || key === "height") && isString(next) && prev === next;
    }
    const xlinkNS = "http://www.w3.org/1999/xlink";
    function patchAttr(el, key, value, isSVG, instance, isBoolean = isSpecialBooleanAttr(key)) {
      if (isSVG && key.startsWith("xlink:")) {
        if (value == null) {
          el.removeAttributeNS(xlinkNS, key.slice(6, key.length));
        } else {
          el.setAttributeNS(xlinkNS, key, value);
        }
      } else {
        if (value == null || isBoolean && !includeBooleanAttr(value)) {
          el.removeAttribute(key);
        } else {
          el.setAttribute(
            key,
            isBoolean ? "" : isSymbol(value) ? String(value) : value
          );
        }
      }
    }
    function patchDOMProp(el, key, value, parentComponent, attrName) {
      if (key === "innerHTML" || key === "textContent") {
        if (value != null) {
          el[key] = key === "innerHTML" ? unsafeToTrustedHTML(value) : value;
        }
        return;
      }
      const tag = el.tagName;
      if (key === "value" && tag !== "PROGRESS" && // custom elements may use _value internally
      !tag.includes("-")) {
        const oldValue = tag === "OPTION" ? el.getAttribute("value") || "" : el.value;
        const newValue = value == null ? (
          // #11647: value should be set as empty string for null and undefined,
          // but <input type="checkbox"> should be set as 'on'.
          el.type === "checkbox" ? "on" : ""
        ) : String(value);
        if (oldValue !== newValue || !("_value" in el)) {
          el.value = newValue;
        }
        if (value == null) {
          el.removeAttribute(key);
        }
        el._value = value;
        return;
      }
      let needRemove = false;
      if (value === "" || value == null) {
        const type = typeof el[key];
        if (type === "boolean") {
          value = includeBooleanAttr(value);
        } else if (value == null && type === "string") {
          value = "";
          needRemove = true;
        } else if (type === "number") {
          value = 0;
          needRemove = true;
        }
      }
      try {
        el[key] = value;
      } catch (e) {
      }
      needRemove && el.removeAttribute(attrName || key);
    }
    function addEventListener(el, event, handler, options) {
      el.addEventListener(event, handler, options);
    }
    function removeEventListener(el, event, handler, options) {
      el.removeEventListener(event, handler, options);
    }
    const veiKey = /* @__PURE__ */ Symbol("_vei");
    function patchEvent(el, rawName, prevValue, nextValue, instance = null) {
      const invokers = el[veiKey] || (el[veiKey] = {});
      const existingInvoker = invokers[rawName];
      if (nextValue && existingInvoker) {
        existingInvoker.value = nextValue;
      } else {
        const [name, options] = parseName(rawName);
        if (nextValue) {
          const invoker = invokers[rawName] = createInvoker(
            nextValue,
            instance
          );
          addEventListener(el, name, invoker, options);
        } else if (existingInvoker) {
          removeEventListener(el, name, existingInvoker, options);
          invokers[rawName] = void 0;
        }
      }
    }
    const optionsModifierRE = /(Once|Passive|Capture)$/;
    const optionsModifierEventRE = /^on:?(?:Once|Passive|Capture)$/;
    function parseName(name) {
      let options;
      let m;
      while ((m = name.match(optionsModifierRE)) && !optionsModifierEventRE.test(name)) {
        if (!options) options = {};
        name = name.slice(0, name.length - m[1].length);
        options[m[1].toLowerCase()] = true;
      }
      const event = name[2] === ":" ? name.slice(3) : hyphenate(name.slice(2));
      return [event, options];
    }
    let cachedNow = 0;
    const p = /* @__PURE__ */ Promise.resolve();
    const getNow = () => cachedNow || (p.then(() => cachedNow = 0), cachedNow = Date.now());
    function createInvoker(initialValue, instance) {
      const invoker = (e) => {
        if (!e._vts) {
          e._vts = Date.now();
        } else if (e._vts <= invoker.attached) {
          return;
        }
        const value = invoker.value;
        if (isArray$1(value)) {
          const originalStop = e.stopImmediatePropagation;
          e.stopImmediatePropagation = () => {
            originalStop.call(e);
            e._stopped = true;
          };
          const handlers = value.slice();
          const args = [e];
          for (let i = 0; i < handlers.length; i++) {
            if (e._stopped) {
              break;
            }
            const handler = handlers[i];
            if (handler) {
              callWithAsyncErrorHandling(
                handler,
                instance,
                5,
                args
              );
            }
          }
        } else {
          callWithAsyncErrorHandling(
            value,
            instance,
            5,
            [e]
          );
        }
      };
      invoker.value = initialValue;
      invoker.attached = getNow();
      return invoker;
    }
    const isNativeOn = (key) => key.charCodeAt(0) === 111 && key.charCodeAt(1) === 110 && // lowercase letter
    key.charCodeAt(2) > 96 && key.charCodeAt(2) < 123;
    const patchProp = (el, key, prevValue, nextValue, namespace, parentComponent) => {
      const isSVG = namespace === "svg";
      if (key === "class") {
        patchClass(el, nextValue, isSVG);
      } else if (key === "style") {
        patchStyle(el, prevValue, nextValue);
      } else if (isOn(key)) {
        if (!isModelListener(key)) {
          patchEvent(el, key, prevValue, nextValue, parentComponent);
        }
      } else if (key[0] === "." ? (key = key.slice(1), true) : key[0] === "^" ? (key = key.slice(1), false) : shouldSetAsProp(el, key, nextValue, isSVG)) {
        patchDOMProp(el, key, nextValue);
        if (!el.tagName.includes("-") && (key === "value" || key === "checked" || key === "selected")) {
          patchAttr(el, key, nextValue, isSVG, parentComponent, key !== "value");
        }
      } else if (
        // #11081 force set props for possible async custom element
        el._isVueCE && // #12408 check if it's declared prop or it's async custom element
        (shouldSetAsPropForVueCE(el, key) || // @ts-expect-error _def is private
        el._def.__asyncLoader && (/[A-Z]/.test(key) || !isString(nextValue)))
      ) {
        patchDOMProp(el, camelize(key), nextValue, parentComponent, key);
      } else {
        if (key === "true-value") {
          el._trueValue = nextValue;
        } else if (key === "false-value") {
          el._falseValue = nextValue;
        }
        patchAttr(el, key, nextValue, isSVG);
      }
    };
    function shouldSetAsProp(el, key, value, isSVG) {
      if (isSVG) {
        if (key === "innerHTML" || key === "textContent") {
          return true;
        }
        if (key in el && isNativeOn(key) && isFunction$1(value)) {
          return true;
        }
        return false;
      }
      if (key === "spellcheck" || key === "draggable" || key === "translate" || key === "autocorrect") {
        return false;
      }
      if (key === "sandbox" && el.tagName === "IFRAME") {
        return false;
      }
      if (key === "form") {
        return false;
      }
      if (key === "list" && el.tagName === "INPUT") {
        return false;
      }
      if (key === "type" && el.tagName === "TEXTAREA") {
        return false;
      }
      if (key === "width" || key === "height") {
        const tag = el.tagName;
        if (tag === "IMG" || tag === "VIDEO" || tag === "CANVAS" || tag === "SOURCE") {
          return false;
        }
      }
      if (isNativeOn(key) && isString(value)) {
        return false;
      }
      return key in el;
    }
    function shouldSetAsPropForVueCE(el, key) {
      const props = (
        // @ts-expect-error _def is private
        el._def.props
      );
      if (!props) {
        return false;
      }
      const camelKey = camelize(key);
      return Array.isArray(props) ? props.some((prop) => camelize(prop) === camelKey) : Object.keys(props).some((prop) => camelize(prop) === camelKey);
    }
    const positionMap = /* @__PURE__ */ new WeakMap();
    const newPositionMap = /* @__PURE__ */ new WeakMap();
    const moveCbKey = /* @__PURE__ */ Symbol("_moveCb");
    const enterCbKey = /* @__PURE__ */ Symbol("_enterCb");
    const decorate = (t) => {
      delete t.props.mode;
      return t;
    };
    const TransitionGroupImpl = /* @__PURE__ */ decorate({
      name: "TransitionGroup",
      props: /* @__PURE__ */ extend({}, TransitionPropsValidators, {
        tag: String,
        moveClass: String
      }),
      setup(props, { slots }) {
        const instance = getCurrentInstance();
        const state = useTransitionState();
        let prevChildren;
        let children;
        onUpdated(() => {
          if (!prevChildren.length) {
            return;
          }
          const moveClass = props.moveClass || `${props.name || "v"}-move`;
          if (!hasCSSTransform(
            prevChildren[0].el,
            instance.vnode.el,
            moveClass
          )) {
            prevChildren = [];
            return;
          }
          prevChildren.forEach(callPendingCbs);
          prevChildren.forEach(recordPosition);
          const movedChildren = prevChildren.filter(applyTranslation);
          forceReflow(instance.vnode.el);
          movedChildren.forEach((c2) => {
            const el = c2.el;
            const style = el.style;
            addTransitionClass(el, moveClass);
            style.transform = style.webkitTransform = style.transitionDuration = "";
            const cb = el[moveCbKey] = (e) => {
              if (e && e.target !== el) {
                return;
              }
              if (!e || e.propertyName.endsWith("transform")) {
                el.removeEventListener("transitionend", cb);
                el[moveCbKey] = null;
                removeTransitionClass(el, moveClass);
              }
            };
            el.addEventListener("transitionend", cb);
          });
          prevChildren = [];
        });
        return () => {
          const rawProps = /* @__PURE__ */ toRaw(props);
          const cssTransitionProps = resolveTransitionProps(rawProps);
          let tag = rawProps.tag || Fragment;
          prevChildren = [];
          if (children) {
            for (let i = 0; i < children.length; i++) {
              const child = children[i];
              if (child.el && child.el instanceof Element && // Hidden v-show nodes have no previous layout box to animate from.
              !child.el[vShowHidden]) {
                prevChildren.push(child);
                setTransitionHooks(
                  child,
                  resolveTransitionHooks(
                    child,
                    cssTransitionProps,
                    state,
                    instance
                  )
                );
                positionMap.set(child, getPosition(child.el));
              }
            }
          }
          children = slots.default ? getTransitionRawChildren(slots.default()) : [];
          for (let i = 0; i < children.length; i++) {
            const child = children[i];
            if (child.key != null) {
              setTransitionHooks(
                child,
                resolveTransitionHooks(child, cssTransitionProps, state, instance)
              );
            }
          }
          return createVNode(tag, null, children);
        };
      }
    });
    const TransitionGroup = TransitionGroupImpl;
    function callPendingCbs(c2) {
      const el = c2.el;
      if (el[moveCbKey]) {
        el[moveCbKey]();
      }
      if (el[enterCbKey]) {
        el[enterCbKey]();
      }
    }
    function recordPosition(c2) {
      newPositionMap.set(c2, getPosition(c2.el));
    }
    function applyTranslation(c2) {
      const oldPos = positionMap.get(c2);
      const newPos = newPositionMap.get(c2);
      const dx = oldPos.left - newPos.left;
      const dy = oldPos.top - newPos.top;
      if (dx || dy) {
        const el = c2.el;
        const s = el.style;
        const rect = el.getBoundingClientRect();
        let scaleX = 1;
        let scaleY = 1;
        if (el.offsetWidth) scaleX = rect.width / el.offsetWidth;
        if (el.offsetHeight) scaleY = rect.height / el.offsetHeight;
        if (!Number.isFinite(scaleX) || scaleX === 0) scaleX = 1;
        if (!Number.isFinite(scaleY) || scaleY === 0) scaleY = 1;
        if (Math.abs(scaleX - 1) < 0.01) scaleX = 1;
        if (Math.abs(scaleY - 1) < 0.01) scaleY = 1;
        s.transform = s.webkitTransform = `translate(${dx / scaleX}px,${dy / scaleY}px)`;
        s.transitionDuration = "0s";
        return c2;
      }
    }
    function getPosition(el) {
      const rect = el.getBoundingClientRect();
      return {
        left: rect.left,
        top: rect.top
      };
    }
    function hasCSSTransform(el, root2, moveClass) {
      const clone = el.cloneNode();
      const _vtc = el[vtcKey];
      if (_vtc) {
        _vtc.forEach((cls) => {
          cls.split(/\s+/).forEach((c2) => c2 && clone.classList.remove(c2));
        });
      }
      moveClass.split(/\s+/).forEach((c2) => c2 && clone.classList.add(c2));
      clone.style.display = "none";
      const container = root2.nodeType === 1 ? root2 : root2.parentNode;
      container.appendChild(clone);
      const { hasTransform } = getTransitionInfo(clone);
      container.removeChild(clone);
      return hasTransform;
    }
    const getModelAssigner = (vnode) => {
      const fn = vnode.props["onUpdate:modelValue"] || false;
      return isArray$1(fn) ? (value) => invokeArrayFns(fn, value) : fn;
    };
    const assignKey = /* @__PURE__ */ Symbol("_assign");
    const vModelSelect = {
      // <select multiple> value need to be deep traversed
      deep: true,
      created(el, { value, modifiers: { number } }, vnode) {
        el._modelValue = value;
        addEventListener(el, "change", () => {
          const selectedVal = Array.prototype.filter.call(el.options, (o) => o.selected).map(
            (o) => number ? looseToNumber(getValue$1(o)) : getValue$1(o)
          );
          const multiple = el.multiple;
          const assignedValue = multiple ? isSet(el._modelValue) ? new Set(selectedVal) : selectedVal : selectedVal[0];
          const pending = el._pendingValue = [
            multiple,
            multiple ? isArray$1(assignedValue) ? selectedVal.slice() : selectedVal : assignedValue
          ];
          try {
            el[assignKey](assignedValue);
          } finally {
            nextTick(() => {
              if (el._pendingValue === pending) {
                el._pendingValue = void 0;
              }
            });
          }
        });
        el[assignKey] = getModelAssigner(vnode);
      },
      // set value in mounted & updated because <select> relies on its children
      // <option>s.
      mounted(el, { value }) {
        setSelected(el, value);
      },
      beforeUpdate(el, { value }, vnode) {
        el._modelValue = value;
        el[assignKey] = getModelAssigner(vnode);
      },
      updated(el, { value }) {
        const pending = el._pendingValue;
        el._pendingValue = void 0;
        if (!pending || pending[0] !== el.multiple || !isSameSelectValue(value, pending[1], pending[0])) {
          setSelected(el, value);
        }
      }
    };
    function isSameSelectValue(value, assignedValue, multiple) {
      if (!multiple) return looseEqual(value, assignedValue);
      if (isArray$1(value)) return looseEqual(value, assignedValue);
      if (isSet(value)) {
        if (value.size !== assignedValue.length) return false;
        for (const item of assignedValue) {
          if (!value.has(item)) return false;
        }
        return true;
      }
      return false;
    }
    function setSelected(el, value) {
      const isMultiple = el.multiple;
      const isArrayValue = isArray$1(value);
      if (isMultiple && !isArrayValue && !isSet(value)) {
        return;
      }
      for (let i = 0, l = el.options.length; i < l; i++) {
        const option = el.options[i];
        const optionValue = getValue$1(option);
        if (isMultiple) {
          if (isArrayValue) {
            const optionType = typeof optionValue;
            if (optionType === "string" || optionType === "number") {
              option.selected = value.some((v) => String(v) === String(optionValue));
            } else {
              option.selected = looseIndexOf(value, optionValue) > -1;
            }
          } else {
            option.selected = value.has(optionValue);
          }
        } else if (looseEqual(getValue$1(option), value)) {
          if (el.selectedIndex !== i) el.selectedIndex = i;
          return;
        }
      }
      if (!isMultiple && el.selectedIndex !== -1) {
        el.selectedIndex = -1;
      }
    }
    function getValue$1(el) {
      return "_value" in el ? el._value : el.value;
    }
    const rendererOptions = /* @__PURE__ */ extend({ patchProp }, nodeOps);
    let renderer;
    function ensureRenderer() {
      return renderer || (renderer = createRenderer(rendererOptions));
    }
    const createApp = ((...args) => {
      const app = ensureRenderer().createApp(...args);
      const { mount: mount2 } = app;
      app.mount = (containerOrSelector) => {
        const container = normalizeContainer(containerOrSelector);
        if (!container) return;
        const component = app._component;
        if (!isFunction$1(component) && !component.render && !component.template) {
          component.template = container.innerHTML;
        }
        if (container.nodeType === 1) {
          container.textContent = "";
        }
        const proxy = mount2(container, false, resolveRootNamespace(container));
        if (container instanceof Element) {
          container.removeAttribute("v-cloak");
          container.setAttribute("data-v-app", "");
        }
        return proxy;
      };
      return app;
    });
    function resolveRootNamespace(container) {
      if (container instanceof SVGElement) {
        return "svg";
      }
      if (typeof MathMLElement === "function" && container instanceof MathMLElement) {
        return "mathml";
      }
    }
    function normalizeContainer(container) {
      if (isString(container)) {
        const res = document.querySelector(container);
        return res;
      }
      return container;
    }
    function plugin(options) {
      let _bPrefix = ".";
      let _ePrefix = "__";
      let _mPrefix = "--";
      let c2;
      if (options) {
        let t = options.blockPrefix;
        if (t) {
          _bPrefix = t;
        }
        t = options.elementPrefix;
        if (t) {
          _ePrefix = t;
        }
        t = options.modifierPrefix;
        if (t) {
          _mPrefix = t;
        }
      }
      const _plugin = {
        install(instance) {
          c2 = instance.c;
          const ctx = instance.context;
          ctx.bem = {};
          ctx.bem.b = null;
          ctx.bem.els = null;
        }
      };
      function b(arg) {
        let memorizedB;
        let memorizedE;
        return {
          before(ctx) {
            memorizedB = ctx.bem.b;
            memorizedE = ctx.bem.els;
            ctx.bem.els = null;
          },
          after(ctx) {
            ctx.bem.b = memorizedB;
            ctx.bem.els = memorizedE;
          },
          $({ context, props }) {
            arg = typeof arg === "string" ? arg : arg({ context, props });
            context.bem.b = arg;
            return `${(props === null || props === void 0 ? void 0 : props.bPrefix) || _bPrefix}${context.bem.b}`;
          }
        };
      }
      function e(arg) {
        let memorizedE;
        return {
          before(ctx) {
            memorizedE = ctx.bem.els;
          },
          after(ctx) {
            ctx.bem.els = memorizedE;
          },
          $({ context, props }) {
            arg = typeof arg === "string" ? arg : arg({ context, props });
            context.bem.els = arg.split(",").map((v) => v.trim());
            return context.bem.els.map((el) => `${(props === null || props === void 0 ? void 0 : props.bPrefix) || _bPrefix}${context.bem.b}${_ePrefix}${el}`).join(", ");
          }
        };
      }
      function m(arg) {
        return {
          $({ context, props }) {
            arg = typeof arg === "string" ? arg : arg({ context, props });
            const modifiers = arg.split(",").map((v) => v.trim());
            function elementToSelector(el) {
              return modifiers.map((modifier) => `&${(props === null || props === void 0 ? void 0 : props.bPrefix) || _bPrefix}${context.bem.b}${el !== void 0 ? `${_ePrefix}${el}` : ""}${_mPrefix}${modifier}`).join(", ");
            }
            const els = context.bem.els;
            if (els !== null) {
              return elementToSelector(els[0]);
            } else {
              return elementToSelector();
            }
          }
        };
      }
      function notM(arg) {
        return {
          $({ context, props }) {
            arg = typeof arg === "string" ? arg : arg({ context, props });
            const els = context.bem.els;
            return `&:not(${(props === null || props === void 0 ? void 0 : props.bPrefix) || _bPrefix}${context.bem.b}${els !== null && els.length > 0 ? `${_ePrefix}${els[0]}` : ""}${_mPrefix}${arg})`;
          }
        };
      }
      const cB2 = ((...args) => c2(b(args[0]), args[1], args[2]));
      const cE2 = ((...args) => c2(e(args[0]), args[1], args[2]));
      const cM2 = ((...args) => c2(m(args[0]), args[1], args[2]));
      const cNotM2 = ((...args) => c2(notM(args[0]), args[1], args[2]));
      Object.assign(_plugin, {
        cB: cB2,
        cE: cE2,
        cM: cM2,
        cNotM: cNotM2
      });
      return _plugin;
    }
    function ampCount(selector) {
      let cnt = 0;
      for (let i = 0; i < selector.length; ++i) {
        if (selector[i] === "&")
          ++cnt;
      }
      return cnt;
    }
    const separatorRegex = /\s*,(?![^(]*\))\s*/g;
    const extraSpaceRegex = /\s+/g;
    function resolveSelectorWithAmp(amp, selector) {
      const nextAmp = [];
      selector.split(separatorRegex).forEach((partialSelector) => {
        let round = ampCount(partialSelector);
        if (!round) {
          amp.forEach((partialAmp) => {
            nextAmp.push(
              // eslint-disable-next-line @typescript-eslint/strict-boolean-expressions
              (partialAmp && partialAmp + " ") + partialSelector
            );
          });
          return;
        } else if (round === 1) {
          amp.forEach((partialAmp) => {
            nextAmp.push(partialSelector.replace("&", partialAmp));
          });
          return;
        }
        let partialNextAmp = [
          partialSelector
        ];
        while (round--) {
          const nextPartialNextAmp = [];
          partialNextAmp.forEach((selectorItr) => {
            amp.forEach((partialAmp) => {
              nextPartialNextAmp.push(selectorItr.replace("&", partialAmp));
            });
          });
          partialNextAmp = nextPartialNextAmp;
        }
        partialNextAmp.forEach((part) => nextAmp.push(part));
      });
      return nextAmp;
    }
    function resolveSelector(amp, selector) {
      const nextAmp = [];
      selector.split(separatorRegex).forEach((partialSelector) => {
        amp.forEach((partialAmp) => {
          nextAmp.push((partialAmp && partialAmp + " ") + partialSelector);
        });
      });
      return nextAmp;
    }
    function parseSelectorPath(selectorPaths) {
      let amp = [""];
      selectorPaths.forEach((selector) => {
        selector = selector && selector.trim();
        if (
          // eslint-disable-next-line @typescript-eslint/strict-boolean-expressions
          !selector
        ) {
          return;
        }
        if (selector.includes("&")) {
          amp = resolveSelectorWithAmp(amp, selector);
        } else {
          amp = resolveSelector(amp, selector);
        }
      });
      return amp.join(", ").replace(extraSpaceRegex, " ");
    }
    function removeElement(el) {
      if (!el)
        return;
      const parentElement = el.parentElement;
      if (parentElement)
        parentElement.removeChild(el);
    }
    function queryElement(id, parent) {
      return (parent !== null && parent !== void 0 ? parent : document.head).querySelector(`style[cssr-id="${id}"]`);
    }
    function createElement(id) {
      const el = document.createElement("style");
      el.setAttribute("cssr-id", id);
      return el;
    }
    function isMediaOrSupports(selector) {
      if (!selector)
        return false;
      return /^\s*@(s|m)/.test(selector);
    }
    const kebabRegex = /[A-Z]/g;
    function kebabCase(pattern) {
      return pattern.replace(kebabRegex, (match) => "-" + match.toLowerCase());
    }
    function unwrapProperty(prop, indent = "  ") {
      if (typeof prop === "object" && prop !== null) {
        return " {\n" + Object.entries(prop).map((v) => {
          return indent + `  ${kebabCase(v[0])}: ${v[1]};`;
        }).join("\n") + "\n" + indent + "}";
      }
      return `: ${prop};`;
    }
    function unwrapProperties(props, instance, params) {
      if (typeof props === "function") {
        return props({
          context: instance.context,
          props: params
        });
      }
      return props;
    }
    function createStyle(selector, props, instance, params) {
      if (!props)
        return "";
      const unwrappedProps = unwrapProperties(props, instance, params);
      if (!unwrappedProps)
        return "";
      if (typeof unwrappedProps === "string") {
        return `${selector} {
${unwrappedProps}
}`;
      }
      const propertyNames = Object.keys(unwrappedProps);
      if (propertyNames.length === 0) {
        if (instance.config.keepEmptyBlock)
          return selector + " {\n}";
        return "";
      }
      const statements = selector ? [
        selector + " {"
      ] : [];
      propertyNames.forEach((propertyName) => {
        const property = unwrappedProps[propertyName];
        if (propertyName === "raw") {
          statements.push("\n" + property + "\n");
          return;
        }
        propertyName = kebabCase(propertyName);
        if (property !== null && property !== void 0) {
          statements.push(`  ${propertyName}${unwrapProperty(property)}`);
        }
      });
      if (selector) {
        statements.push("}");
      }
      return statements.join("\n");
    }
    function loopCNodeListWithCallback(children, options, callback) {
      if (!children)
        return;
      children.forEach((child) => {
        if (Array.isArray(child)) {
          loopCNodeListWithCallback(child, options, callback);
        } else if (typeof child === "function") {
          const grandChildren = child(options);
          if (Array.isArray(grandChildren)) {
            loopCNodeListWithCallback(grandChildren, options, callback);
          } else if (grandChildren) {
            callback(grandChildren);
          }
        } else if (child) {
          callback(child);
        }
      });
    }
    function traverseCNode(node, selectorPaths, styles, instance, params) {
      const $ = node.$;
      let blockSelector = "";
      if (!$ || typeof $ === "string") {
        if (isMediaOrSupports($)) {
          blockSelector = $;
        } else {
          selectorPaths.push($);
        }
      } else if (typeof $ === "function") {
        const selector2 = $({
          context: instance.context,
          props: params
        });
        if (isMediaOrSupports(selector2)) {
          blockSelector = selector2;
        } else {
          selectorPaths.push(selector2);
        }
      } else {
        if ($.before)
          $.before(instance.context);
        if (!$.$ || typeof $.$ === "string") {
          if (isMediaOrSupports($.$)) {
            blockSelector = $.$;
          } else {
            selectorPaths.push($.$);
          }
        } else if ($.$) {
          const selector2 = $.$({
            context: instance.context,
            props: params
          });
          if (isMediaOrSupports(selector2)) {
            blockSelector = selector2;
          } else {
            selectorPaths.push(selector2);
          }
        }
      }
      const selector = parseSelectorPath(selectorPaths);
      const style = createStyle(selector, node.props, instance, params);
      if (blockSelector) {
        styles.push(`${blockSelector} {`);
      } else if (style.length) {
        styles.push(style);
      }
      if (node.children) {
        loopCNodeListWithCallback(node.children, {
          context: instance.context,
          props: params
        }, (childNode) => {
          if (typeof childNode === "string") {
            const style2 = createStyle(selector, { raw: childNode }, instance, params);
            styles.push(style2);
          } else {
            traverseCNode(childNode, selectorPaths, styles, instance, params);
          }
        });
      }
      selectorPaths.pop();
      if (blockSelector) {
        styles.push("}");
      }
      if ($ && $.after)
        $.after(instance.context);
    }
    function render(node, instance, props) {
      const styles = [];
      traverseCNode(node, [], styles, instance, props);
      return styles.join("\n\n");
    }
    function murmur2(str) {
      var h2 = 0;
      var k, i = 0, len = str.length;
      for (; len >= 4; ++i, len -= 4) {
        k = str.charCodeAt(i) & 255 | (str.charCodeAt(++i) & 255) << 8 | (str.charCodeAt(++i) & 255) << 16 | (str.charCodeAt(++i) & 255) << 24;
        k = /* Math.imul(k, m): */
        (k & 65535) * 1540483477 + ((k >>> 16) * 59797 << 16);
        k ^= /* k >>> r: */
        k >>> 24;
        h2 = /* Math.imul(k, m): */
        (k & 65535) * 1540483477 + ((k >>> 16) * 59797 << 16) ^ /* Math.imul(h, m): */
        (h2 & 65535) * 1540483477 + ((h2 >>> 16) * 59797 << 16);
      }
      switch (len) {
        case 3:
          h2 ^= (str.charCodeAt(i + 2) & 255) << 16;
        case 2:
          h2 ^= (str.charCodeAt(i + 1) & 255) << 8;
        case 1:
          h2 ^= str.charCodeAt(i) & 255;
          h2 = /* Math.imul(h, m): */
          (h2 & 65535) * 1540483477 + ((h2 >>> 16) * 59797 << 16);
      }
      h2 ^= h2 >>> 13;
      h2 = /* Math.imul(h, m): */
      (h2 & 65535) * 1540483477 + ((h2 >>> 16) * 59797 << 16);
      return ((h2 ^ h2 >>> 15) >>> 0).toString(36);
    }
    if (typeof window !== "undefined") {
      window.__cssrContext = {};
    }
    function unmount(instance, node, id, parent) {
      const { els } = node;
      if (id === void 0) {
        els.forEach(removeElement);
        node.els = [];
      } else {
        const target = queryElement(id, parent);
        if (target && els.includes(target)) {
          removeElement(target);
          node.els = els.filter((el) => el !== target);
        }
      }
    }
    function addElementToList(els, target) {
      els.push(target);
    }
    function mount(instance, node, id, props, head, force, anchorMetaName, parent, ssrAdapter2) {
      let style;
      if (id === void 0) {
        style = node.render(props);
        id = murmur2(style);
      }
      if (ssrAdapter2) {
        ssrAdapter2.adapter(id, style !== null && style !== void 0 ? style : node.render(props));
        return;
      }
      if (parent === void 0) {
        parent = document.head;
      }
      const queriedTarget = queryElement(id, parent);
      if (queriedTarget !== null && !force) {
        return queriedTarget;
      }
      const target = queriedTarget !== null && queriedTarget !== void 0 ? queriedTarget : createElement(id);
      if (style === void 0)
        style = node.render(props);
      target.textContent = style;
      if (queriedTarget !== null)
        return queriedTarget;
      if (anchorMetaName) {
        const anchorMetaEl = parent.querySelector(`meta[name="${anchorMetaName}"]`);
        if (anchorMetaEl) {
          parent.insertBefore(target, anchorMetaEl);
          addElementToList(node.els, target);
          return target;
        }
      }
      if (head) {
        parent.insertBefore(target, parent.querySelector("style, link"));
      } else {
        parent.appendChild(target);
      }
      addElementToList(node.els, target);
      return target;
    }
    function wrappedRender(props) {
      return render(this, this.instance, props);
    }
    function wrappedMount(options = {}) {
      const { id, ssr, props, head = false, force = false, anchorMetaName, parent } = options;
      const targetElement = mount(this.instance, this, id, props, head, force, anchorMetaName, parent, ssr);
      return targetElement;
    }
    function wrappedUnmount(options = {}) {
      const { id, parent } = options;
      unmount(this.instance, this, id, parent);
    }
    const createCNode = function(instance, $, props, children) {
      return {
        instance,
        $,
        props,
        children,
        els: [],
        render: wrappedRender,
        mount: wrappedMount,
        unmount: wrappedUnmount
      };
    };
    const c$1 = function(instance, $, props, children) {
      if (Array.isArray($)) {
        return createCNode(instance, { $: null }, null, $);
      } else if (Array.isArray(props)) {
        return createCNode(instance, $, null, props);
      } else if (Array.isArray(children)) {
        return createCNode(instance, $, props, children);
      } else {
        return createCNode(instance, $, props, null);
      }
    };
    function CssRender(config = {}) {
      const cssr2 = {
        c: ((...args) => c$1(cssr2, ...args)),
        use: (plugin2, ...args) => plugin2.install(cssr2, ...args),
        find: queryElement,
        context: {},
        config
      };
      return cssr2;
    }
    function exists(id, ssr) {
      if (id === void 0)
        return false;
      if (ssr) {
        const { context: { ids } } = ssr;
        return ids.has(id);
      }
      return queryElement(id) !== null;
    }
    const prefix$1 = `.n-`;
    const elementPrefix = "__";
    const modifierPrefix = "--";
    const cssr = CssRender();
    const plugin$1 = plugin({
      blockPrefix: prefix$1,
      elementPrefix,
      modifierPrefix
    });
    cssr.use(plugin$1);
    const {
      c,
      find
    } = cssr;
    const {
      cB,
      cE,
      cM,
      cNotM
    } = plugin$1;
    function createKey(prefix2, suffix2) {
      return prefix2 + (suffix2 === "default" ? "" : suffix2.replace(/^[a-z]/, (startChar) => startChar.toUpperCase()));
    }
    var freeGlobal = typeof global == "object" && global && global.Object === Object && global;
    var freeSelf = typeof self == "object" && self && self.Object === Object && self;
    var root = freeGlobal || freeSelf || Function("return this")();
    var Symbol$1 = root.Symbol;
    var objectProto$9 = Object.prototype;
    var hasOwnProperty$7 = objectProto$9.hasOwnProperty;
    var nativeObjectToString$1 = objectProto$9.toString;
    var symToStringTag$1 = Symbol$1 ? Symbol$1.toStringTag : void 0;
    function getRawTag(value) {
      var isOwn = hasOwnProperty$7.call(value, symToStringTag$1), tag = value[symToStringTag$1];
      try {
        value[symToStringTag$1] = void 0;
        var unmasked = true;
      } catch (e) {
      }
      var result = nativeObjectToString$1.call(value);
      if (unmasked) {
        if (isOwn) {
          value[symToStringTag$1] = tag;
        } else {
          delete value[symToStringTag$1];
        }
      }
      return result;
    }
    var objectProto$8 = Object.prototype;
    var nativeObjectToString = objectProto$8.toString;
    function objectToString(value) {
      return nativeObjectToString.call(value);
    }
    var nullTag = "[object Null]", undefinedTag = "[object Undefined]";
    var symToStringTag = Symbol$1 ? Symbol$1.toStringTag : void 0;
    function baseGetTag(value) {
      if (value == null) {
        return value === void 0 ? undefinedTag : nullTag;
      }
      return symToStringTag && symToStringTag in Object(value) ? getRawTag(value) : objectToString(value);
    }
    function isObjectLike(value) {
      return value != null && typeof value == "object";
    }
    var isArray = Array.isArray;
    function isObject(value) {
      var type = typeof value;
      return value != null && (type == "object" || type == "function");
    }
    function identity(value) {
      return value;
    }
    var asyncTag = "[object AsyncFunction]", funcTag$1 = "[object Function]", genTag = "[object GeneratorFunction]", proxyTag = "[object Proxy]";
    function isFunction(value) {
      if (!isObject(value)) {
        return false;
      }
      var tag = baseGetTag(value);
      return tag == funcTag$1 || tag == genTag || tag == asyncTag || tag == proxyTag;
    }
    var coreJsData = root["__core-js_shared__"];
    var maskSrcKey = (function() {
      var uid2 = /[^.]+$/.exec(coreJsData && coreJsData.keys && coreJsData.keys.IE_PROTO || "");
      return uid2 ? "Symbol(src)_1." + uid2 : "";
    })();
    function isMasked(func) {
      return !!maskSrcKey && maskSrcKey in func;
    }
    var funcProto$2 = Function.prototype;
    var funcToString$2 = funcProto$2.toString;
    function toSource(func) {
      if (func != null) {
        try {
          return funcToString$2.call(func);
        } catch (e) {
        }
        try {
          return func + "";
        } catch (e) {
        }
      }
      return "";
    }
    var reRegExpChar = /[\\^$.*+?()[\]{}|]/g;
    var reIsHostCtor = /^\[object .+?Constructor\]$/;
    var funcProto$1 = Function.prototype, objectProto$7 = Object.prototype;
    var funcToString$1 = funcProto$1.toString;
    var hasOwnProperty$6 = objectProto$7.hasOwnProperty;
    var reIsNative = RegExp(
      "^" + funcToString$1.call(hasOwnProperty$6).replace(reRegExpChar, "\\$&").replace(/hasOwnProperty|(function).*?(?=\\\()| for .+?(?=\\\])/g, "$1.*?") + "$"
    );
    function baseIsNative(value) {
      if (!isObject(value) || isMasked(value)) {
        return false;
      }
      var pattern = isFunction(value) ? reIsNative : reIsHostCtor;
      return pattern.test(toSource(value));
    }
    function getValue(object, key) {
      return object == null ? void 0 : object[key];
    }
    function getNative(object, key) {
      var value = getValue(object, key);
      return baseIsNative(value) ? value : void 0;
    }
    var objectCreate = Object.create;
    var baseCreate = /* @__PURE__ */ (function() {
      function object() {
      }
      return function(proto) {
        if (!isObject(proto)) {
          return {};
        }
        if (objectCreate) {
          return objectCreate(proto);
        }
        object.prototype = proto;
        var result = new object();
        object.prototype = void 0;
        return result;
      };
    })();
    function apply(func, thisArg, args) {
      switch (args.length) {
        case 0:
          return func.call(thisArg);
        case 1:
          return func.call(thisArg, args[0]);
        case 2:
          return func.call(thisArg, args[0], args[1]);
        case 3:
          return func.call(thisArg, args[0], args[1], args[2]);
      }
      return func.apply(thisArg, args);
    }
    function copyArray(source, array) {
      var index = -1, length = source.length;
      array || (array = Array(length));
      while (++index < length) {
        array[index] = source[index];
      }
      return array;
    }
    var HOT_COUNT = 800, HOT_SPAN = 16;
    var nativeNow = Date.now;
    function shortOut(func) {
      var count = 0, lastCalled = 0;
      return function() {
        var stamp = nativeNow(), remaining = HOT_SPAN - (stamp - lastCalled);
        lastCalled = stamp;
        if (remaining > 0) {
          if (++count >= HOT_COUNT) {
            return arguments[0];
          }
        } else {
          count = 0;
        }
        return func.apply(void 0, arguments);
      };
    }
    function constant(value) {
      return function() {
        return value;
      };
    }
    var defineProperty = (function() {
      try {
        var func = getNative(Object, "defineProperty");
        func({}, "", {});
        return func;
      } catch (e) {
      }
    })();
    var baseSetToString = !defineProperty ? identity : function(func, string) {
      return defineProperty(func, "toString", {
        "configurable": true,
        "enumerable": false,
        "value": constant(string),
        "writable": true
      });
    };
    var setToString = shortOut(baseSetToString);
    var MAX_SAFE_INTEGER$1 = 9007199254740991;
    var reIsUint = /^(?:0|[1-9]\d*)$/;
    function isIndex(value, length) {
      var type = typeof value;
      length = length == null ? MAX_SAFE_INTEGER$1 : length;
      return !!length && (type == "number" || type != "symbol" && reIsUint.test(value)) && (value > -1 && value % 1 == 0 && value < length);
    }
    function baseAssignValue(object, key, value) {
      if (key == "__proto__" && defineProperty) {
        defineProperty(object, key, {
          "configurable": true,
          "enumerable": true,
          "value": value,
          "writable": true
        });
      } else {
        object[key] = value;
      }
    }
    function eq(value, other) {
      return value === other || value !== value && other !== other;
    }
    var objectProto$6 = Object.prototype;
    var hasOwnProperty$5 = objectProto$6.hasOwnProperty;
    function assignValue(object, key, value) {
      var objValue = object[key];
      if (!(hasOwnProperty$5.call(object, key) && eq(objValue, value)) || value === void 0 && !(key in object)) {
        baseAssignValue(object, key, value);
      }
    }
    function copyObject(source, props, object, customizer) {
      var isNew = !object;
      object || (object = {});
      var index = -1, length = props.length;
      while (++index < length) {
        var key = props[index];
        var newValue = void 0;
        if (newValue === void 0) {
          newValue = source[key];
        }
        if (isNew) {
          baseAssignValue(object, key, newValue);
        } else {
          assignValue(object, key, newValue);
        }
      }
      return object;
    }
    var nativeMax = Math.max;
    function overRest(func, start, transform) {
      start = nativeMax(start === void 0 ? func.length - 1 : start, 0);
      return function() {
        var args = arguments, index = -1, length = nativeMax(args.length - start, 0), array = Array(length);
        while (++index < length) {
          array[index] = args[start + index];
        }
        index = -1;
        var otherArgs = Array(start + 1);
        while (++index < start) {
          otherArgs[index] = args[index];
        }
        otherArgs[start] = transform(array);
        return apply(func, this, otherArgs);
      };
    }
    function baseRest(func, start) {
      return setToString(overRest(func, start, identity), func + "");
    }
    var MAX_SAFE_INTEGER = 9007199254740991;
    function isLength(value) {
      return typeof value == "number" && value > -1 && value % 1 == 0 && value <= MAX_SAFE_INTEGER;
    }
    function isArrayLike(value) {
      return value != null && isLength(value.length) && !isFunction(value);
    }
    function isIterateeCall(value, index, object) {
      if (!isObject(object)) {
        return false;
      }
      var type = typeof index;
      if (type == "number" ? isArrayLike(object) && isIndex(index, object.length) : type == "string" && index in object) {
        return eq(object[index], value);
      }
      return false;
    }
    function createAssigner(assigner) {
      return baseRest(function(object, sources) {
        var index = -1, length = sources.length, customizer = length > 1 ? sources[length - 1] : void 0, guard = length > 2 ? sources[2] : void 0;
        customizer = assigner.length > 3 && typeof customizer == "function" ? (length--, customizer) : void 0;
        if (guard && isIterateeCall(sources[0], sources[1], guard)) {
          customizer = length < 3 ? void 0 : customizer;
          length = 1;
        }
        object = Object(object);
        while (++index < length) {
          var source = sources[index];
          if (source) {
            assigner(object, source, index, customizer);
          }
        }
        return object;
      });
    }
    var objectProto$5 = Object.prototype;
    function isPrototype(value) {
      var Ctor = value && value.constructor, proto = typeof Ctor == "function" && Ctor.prototype || objectProto$5;
      return value === proto;
    }
    function baseTimes(n, iteratee) {
      var index = -1, result = Array(n);
      while (++index < n) {
        result[index] = iteratee(index);
      }
      return result;
    }
    var argsTag$1 = "[object Arguments]";
    function baseIsArguments(value) {
      return isObjectLike(value) && baseGetTag(value) == argsTag$1;
    }
    var objectProto$4 = Object.prototype;
    var hasOwnProperty$4 = objectProto$4.hasOwnProperty;
    var propertyIsEnumerable = objectProto$4.propertyIsEnumerable;
    var isArguments = baseIsArguments(/* @__PURE__ */ (function() {
      return arguments;
    })()) ? baseIsArguments : function(value) {
      return isObjectLike(value) && hasOwnProperty$4.call(value, "callee") && !propertyIsEnumerable.call(value, "callee");
    };
    function stubFalse() {
      return false;
    }
    var freeExports$2 = typeof exports == "object" && exports && !exports.nodeType && exports;
    var freeModule$2 = freeExports$2 && typeof module == "object" && module && !module.nodeType && module;
    var moduleExports$2 = freeModule$2 && freeModule$2.exports === freeExports$2;
    var Buffer$1 = moduleExports$2 ? root.Buffer : void 0;
    var nativeIsBuffer = Buffer$1 ? Buffer$1.isBuffer : void 0;
    var isBuffer = nativeIsBuffer || stubFalse;
    var argsTag = "[object Arguments]", arrayTag = "[object Array]", boolTag = "[object Boolean]", dateTag = "[object Date]", errorTag = "[object Error]", funcTag = "[object Function]", mapTag = "[object Map]", numberTag = "[object Number]", objectTag$1 = "[object Object]", regexpTag = "[object RegExp]", setTag = "[object Set]", stringTag = "[object String]", weakMapTag = "[object WeakMap]";
    var arrayBufferTag = "[object ArrayBuffer]", dataViewTag = "[object DataView]", float32Tag = "[object Float32Array]", float64Tag = "[object Float64Array]", int8Tag = "[object Int8Array]", int16Tag = "[object Int16Array]", int32Tag = "[object Int32Array]", uint8Tag = "[object Uint8Array]", uint8ClampedTag = "[object Uint8ClampedArray]", uint16Tag = "[object Uint16Array]", uint32Tag = "[object Uint32Array]";
    var typedArrayTags = {};
    typedArrayTags[float32Tag] = typedArrayTags[float64Tag] = typedArrayTags[int8Tag] = typedArrayTags[int16Tag] = typedArrayTags[int32Tag] = typedArrayTags[uint8Tag] = typedArrayTags[uint8ClampedTag] = typedArrayTags[uint16Tag] = typedArrayTags[uint32Tag] = true;
    typedArrayTags[argsTag] = typedArrayTags[arrayTag] = typedArrayTags[arrayBufferTag] = typedArrayTags[boolTag] = typedArrayTags[dataViewTag] = typedArrayTags[dateTag] = typedArrayTags[errorTag] = typedArrayTags[funcTag] = typedArrayTags[mapTag] = typedArrayTags[numberTag] = typedArrayTags[objectTag$1] = typedArrayTags[regexpTag] = typedArrayTags[setTag] = typedArrayTags[stringTag] = typedArrayTags[weakMapTag] = false;
    function baseIsTypedArray(value) {
      return isObjectLike(value) && isLength(value.length) && !!typedArrayTags[baseGetTag(value)];
    }
    function baseUnary(func) {
      return function(value) {
        return func(value);
      };
    }
    var freeExports$1 = typeof exports == "object" && exports && !exports.nodeType && exports;
    var freeModule$1 = freeExports$1 && typeof module == "object" && module && !module.nodeType && module;
    var moduleExports$1 = freeModule$1 && freeModule$1.exports === freeExports$1;
    var freeProcess = moduleExports$1 && freeGlobal.process;
    var nodeUtil = (function() {
      try {
        var types = freeModule$1 && freeModule$1.require && freeModule$1.require("util").types;
        if (types) {
          return types;
        }
        return freeProcess && freeProcess.binding && freeProcess.binding("util");
      } catch (e) {
      }
    })();
    var nodeIsTypedArray = nodeUtil && nodeUtil.isTypedArray;
    var isTypedArray = nodeIsTypedArray ? baseUnary(nodeIsTypedArray) : baseIsTypedArray;
    function arrayLikeKeys(value, inherited) {
      var isArr = isArray(value), isArg = !isArr && isArguments(value), isBuff = !isArr && !isArg && isBuffer(value), isType = !isArr && !isArg && !isBuff && isTypedArray(value), skipIndexes = isArr || isArg || isBuff || isType, result = skipIndexes ? baseTimes(value.length, String) : [], length = result.length;
      for (var key in value) {
        if (!(skipIndexes && // Safari 9 has enumerable `arguments.length` in strict mode.
        (key == "length" || // Node.js 0.10 has enumerable non-index properties on buffers.
        isBuff && (key == "offset" || key == "parent") || // PhantomJS 2 has enumerable non-index properties on typed arrays.
        isType && (key == "buffer" || key == "byteLength" || key == "byteOffset") || // Skip index properties.
        isIndex(key, length)))) {
          result.push(key);
        }
      }
      return result;
    }
    function overArg(func, transform) {
      return function(arg) {
        return func(transform(arg));
      };
    }
    function nativeKeysIn(object) {
      var result = [];
      if (object != null) {
        for (var key in Object(object)) {
          result.push(key);
        }
      }
      return result;
    }
    var objectProto$3 = Object.prototype;
    var hasOwnProperty$3 = objectProto$3.hasOwnProperty;
    function baseKeysIn(object) {
      if (!isObject(object)) {
        return nativeKeysIn(object);
      }
      var isProto = isPrototype(object), result = [];
      for (var key in object) {
        if (!(key == "constructor" && (isProto || !hasOwnProperty$3.call(object, key)))) {
          result.push(key);
        }
      }
      return result;
    }
    function keysIn(object) {
      return isArrayLike(object) ? arrayLikeKeys(object) : baseKeysIn(object);
    }
    var nativeCreate = getNative(Object, "create");
    function hashClear() {
      this.__data__ = nativeCreate ? nativeCreate(null) : {};
      this.size = 0;
    }
    function hashDelete(key) {
      var result = this.has(key) && delete this.__data__[key];
      this.size -= result ? 1 : 0;
      return result;
    }
    var HASH_UNDEFINED$1 = "__lodash_hash_undefined__";
    var objectProto$2 = Object.prototype;
    var hasOwnProperty$2 = objectProto$2.hasOwnProperty;
    function hashGet(key) {
      var data = this.__data__;
      if (nativeCreate) {
        var result = data[key];
        return result === HASH_UNDEFINED$1 ? void 0 : result;
      }
      return hasOwnProperty$2.call(data, key) ? data[key] : void 0;
    }
    var objectProto$1 = Object.prototype;
    var hasOwnProperty$1 = objectProto$1.hasOwnProperty;
    function hashHas(key) {
      var data = this.__data__;
      return nativeCreate ? data[key] !== void 0 : hasOwnProperty$1.call(data, key);
    }
    var HASH_UNDEFINED = "__lodash_hash_undefined__";
    function hashSet(key, value) {
      var data = this.__data__;
      this.size += this.has(key) ? 0 : 1;
      data[key] = nativeCreate && value === void 0 ? HASH_UNDEFINED : value;
      return this;
    }
    function Hash(entries) {
      var index = -1, length = entries == null ? 0 : entries.length;
      this.clear();
      while (++index < length) {
        var entry = entries[index];
        this.set(entry[0], entry[1]);
      }
    }
    Hash.prototype.clear = hashClear;
    Hash.prototype["delete"] = hashDelete;
    Hash.prototype.get = hashGet;
    Hash.prototype.has = hashHas;
    Hash.prototype.set = hashSet;
    function listCacheClear() {
      this.__data__ = [];
      this.size = 0;
    }
    function assocIndexOf(array, key) {
      var length = array.length;
      while (length--) {
        if (eq(array[length][0], key)) {
          return length;
        }
      }
      return -1;
    }
    var arrayProto = Array.prototype;
    var splice = arrayProto.splice;
    function listCacheDelete(key) {
      var data = this.__data__, index = assocIndexOf(data, key);
      if (index < 0) {
        return false;
      }
      var lastIndex = data.length - 1;
      if (index == lastIndex) {
        data.pop();
      } else {
        splice.call(data, index, 1);
      }
      --this.size;
      return true;
    }
    function listCacheGet(key) {
      var data = this.__data__, index = assocIndexOf(data, key);
      return index < 0 ? void 0 : data[index][1];
    }
    function listCacheHas(key) {
      return assocIndexOf(this.__data__, key) > -1;
    }
    function listCacheSet(key, value) {
      var data = this.__data__, index = assocIndexOf(data, key);
      if (index < 0) {
        ++this.size;
        data.push([key, value]);
      } else {
        data[index][1] = value;
      }
      return this;
    }
    function ListCache(entries) {
      var index = -1, length = entries == null ? 0 : entries.length;
      this.clear();
      while (++index < length) {
        var entry = entries[index];
        this.set(entry[0], entry[1]);
      }
    }
    ListCache.prototype.clear = listCacheClear;
    ListCache.prototype["delete"] = listCacheDelete;
    ListCache.prototype.get = listCacheGet;
    ListCache.prototype.has = listCacheHas;
    ListCache.prototype.set = listCacheSet;
    var Map$1 = getNative(root, "Map");
    function mapCacheClear() {
      this.size = 0;
      this.__data__ = {
        "hash": new Hash(),
        "map": new (Map$1 || ListCache)(),
        "string": new Hash()
      };
    }
    function isKeyable(value) {
      var type = typeof value;
      return type == "string" || type == "number" || type == "symbol" || type == "boolean" ? value !== "__proto__" : value === null;
    }
    function getMapData(map, key) {
      var data = map.__data__;
      return isKeyable(key) ? data[typeof key == "string" ? "string" : "hash"] : data.map;
    }
    function mapCacheDelete(key) {
      var result = getMapData(this, key)["delete"](key);
      this.size -= result ? 1 : 0;
      return result;
    }
    function mapCacheGet(key) {
      return getMapData(this, key).get(key);
    }
    function mapCacheHas(key) {
      return getMapData(this, key).has(key);
    }
    function mapCacheSet(key, value) {
      var data = getMapData(this, key), size = data.size;
      data.set(key, value);
      this.size += data.size == size ? 0 : 1;
      return this;
    }
    function MapCache(entries) {
      var index = -1, length = entries == null ? 0 : entries.length;
      this.clear();
      while (++index < length) {
        var entry = entries[index];
        this.set(entry[0], entry[1]);
      }
    }
    MapCache.prototype.clear = mapCacheClear;
    MapCache.prototype["delete"] = mapCacheDelete;
    MapCache.prototype.get = mapCacheGet;
    MapCache.prototype.has = mapCacheHas;
    MapCache.prototype.set = mapCacheSet;
    var getPrototype = overArg(Object.getPrototypeOf, Object);
    var objectTag = "[object Object]";
    var funcProto = Function.prototype, objectProto = Object.prototype;
    var funcToString = funcProto.toString;
    var hasOwnProperty = objectProto.hasOwnProperty;
    var objectCtorString = funcToString.call(Object);
    function isPlainObject(value) {
      if (!isObjectLike(value) || baseGetTag(value) != objectTag) {
        return false;
      }
      var proto = getPrototype(value);
      if (proto === null) {
        return true;
      }
      var Ctor = hasOwnProperty.call(proto, "constructor") && proto.constructor;
      return typeof Ctor == "function" && Ctor instanceof Ctor && funcToString.call(Ctor) == objectCtorString;
    }
    function stackClear() {
      this.__data__ = new ListCache();
      this.size = 0;
    }
    function stackDelete(key) {
      var data = this.__data__, result = data["delete"](key);
      this.size = data.size;
      return result;
    }
    function stackGet(key) {
      return this.__data__.get(key);
    }
    function stackHas(key) {
      return this.__data__.has(key);
    }
    var LARGE_ARRAY_SIZE = 200;
    function stackSet(key, value) {
      var data = this.__data__;
      if (data instanceof ListCache) {
        var pairs = data.__data__;
        if (!Map$1 || pairs.length < LARGE_ARRAY_SIZE - 1) {
          pairs.push([key, value]);
          this.size = ++data.size;
          return this;
        }
        data = this.__data__ = new MapCache(pairs);
      }
      data.set(key, value);
      this.size = data.size;
      return this;
    }
    function Stack(entries) {
      var data = this.__data__ = new ListCache(entries);
      this.size = data.size;
    }
    Stack.prototype.clear = stackClear;
    Stack.prototype["delete"] = stackDelete;
    Stack.prototype.get = stackGet;
    Stack.prototype.has = stackHas;
    Stack.prototype.set = stackSet;
    var freeExports = typeof exports == "object" && exports && !exports.nodeType && exports;
    var freeModule = freeExports && typeof module == "object" && module && !module.nodeType && module;
    var moduleExports = freeModule && freeModule.exports === freeExports;
    var Buffer2 = moduleExports ? root.Buffer : void 0;
    Buffer2 ? Buffer2.allocUnsafe : void 0;
    function cloneBuffer(buffer, isDeep) {
      {
        return buffer.slice();
      }
    }
    var Uint8Array$1 = root.Uint8Array;
    function cloneArrayBuffer(arrayBuffer) {
      var result = new arrayBuffer.constructor(arrayBuffer.byteLength);
      new Uint8Array$1(result).set(new Uint8Array$1(arrayBuffer));
      return result;
    }
    function cloneTypedArray(typedArray, isDeep) {
      var buffer = cloneArrayBuffer(typedArray.buffer);
      return new typedArray.constructor(buffer, typedArray.byteOffset, typedArray.length);
    }
    function initCloneObject(object) {
      return typeof object.constructor == "function" && !isPrototype(object) ? baseCreate(getPrototype(object)) : {};
    }
    function createBaseFor(fromRight) {
      return function(object, iteratee, keysFunc) {
        var index = -1, iterable = Object(object), props = keysFunc(object), length = props.length;
        while (length--) {
          var key = props[++index];
          if (iteratee(iterable[key], key, iterable) === false) {
            break;
          }
        }
        return object;
      };
    }
    var baseFor = createBaseFor();
    function assignMergeValue(object, key, value) {
      if (value !== void 0 && !eq(object[key], value) || value === void 0 && !(key in object)) {
        baseAssignValue(object, key, value);
      }
    }
    function isArrayLikeObject(value) {
      return isObjectLike(value) && isArrayLike(value);
    }
    function safeGet(object, key) {
      if (key === "constructor" && typeof object[key] === "function") {
        return;
      }
      if (key == "__proto__") {
        return;
      }
      return object[key];
    }
    function toPlainObject(value) {
      return copyObject(value, keysIn(value));
    }
    function baseMergeDeep(object, source, key, srcIndex, mergeFunc, customizer, stack2) {
      var objValue = safeGet(object, key), srcValue = safeGet(source, key), stacked = stack2.get(srcValue);
      if (stacked) {
        assignMergeValue(object, key, stacked);
        return;
      }
      var newValue = customizer ? customizer(objValue, srcValue, key + "", object, source, stack2) : void 0;
      var isCommon = newValue === void 0;
      if (isCommon) {
        var isArr = isArray(srcValue), isBuff = !isArr && isBuffer(srcValue), isTyped = !isArr && !isBuff && isTypedArray(srcValue);
        newValue = srcValue;
        if (isArr || isBuff || isTyped) {
          if (isArray(objValue)) {
            newValue = objValue;
          } else if (isArrayLikeObject(objValue)) {
            newValue = copyArray(objValue);
          } else if (isBuff) {
            isCommon = false;
            newValue = cloneBuffer(srcValue);
          } else if (isTyped) {
            isCommon = false;
            newValue = cloneTypedArray(srcValue);
          } else {
            newValue = [];
          }
        } else if (isPlainObject(srcValue) || isArguments(srcValue)) {
          newValue = objValue;
          if (isArguments(objValue)) {
            newValue = toPlainObject(objValue);
          } else if (!isObject(objValue) || isFunction(objValue)) {
            newValue = initCloneObject(srcValue);
          }
        } else {
          isCommon = false;
        }
      }
      if (isCommon) {
        stack2.set(srcValue, newValue);
        mergeFunc(newValue, srcValue, srcIndex, customizer, stack2);
        stack2["delete"](srcValue);
      }
      assignMergeValue(object, key, newValue);
    }
    function baseMerge(object, source, srcIndex, customizer, stack2) {
      if (object === source) {
        return;
      }
      baseFor(source, function(srcValue, key) {
        stack2 || (stack2 = new Stack());
        if (isObject(srcValue)) {
          baseMergeDeep(object, source, key, srcIndex, baseMerge, customizer, stack2);
        } else {
          var newValue = customizer ? customizer(safeGet(object, key), srcValue, key + "", object, source, stack2) : void 0;
          if (newValue === void 0) {
            newValue = srcValue;
          }
          assignMergeValue(object, key, newValue);
        }
      }, keysIn);
    }
    var merge = createAssigner(function(object, source, srcIndex) {
      baseMerge(object, source, srcIndex);
    });
    function warn(location2, message) {
      console.error(`[naive/${location2}]: ${message}`);
    }
    function throwError(location2, message) {
      throw new Error(`[naive/${location2}]: ${message}`);
    }
    function createInjectionKey(key) {
      return key;
    }
    const configProviderInjectionKey = createInjectionKey("n-config-provider");
    function useConfig(props = {}, options = {
      defaultBordered: true
    }) {
      const NConfigProvider = inject(configProviderInjectionKey, null);
      return {
        inlineThemeDisabled: NConfigProvider?.inlineThemeDisabled,
        mergedRtlRef: NConfigProvider?.mergedRtlRef,
        mergedComponentPropsRef: NConfigProvider?.mergedComponentPropsRef,
        mergedBreakpointsRef: NConfigProvider?.mergedBreakpointsRef,
        mergedBorderedRef: computed(() => {
          const {
            bordered
          } = props;
          if (bordered !== void 0) return bordered;
          return NConfigProvider?.mergedBorderedRef.value ?? options.defaultBordered ?? true;
        }),
        mergedClsPrefixRef: NConfigProvider ? NConfigProvider.mergedClsPrefixRef : /* @__PURE__ */ shallowRef("n"),
        namespaceRef: computed(() => NConfigProvider?.mergedNamespaceRef.value)
      };
    }
    const cssrAnchorMetaName = "naive-ui-style";
    var _common_default$F = {
      fontFamily: 'v-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol"',
      fontFamilyMono: "v-mono, SFMono-Regular, Menlo, Consolas, Courier, monospace",
      fontWeight: "400",
      fontWeightStrong: "500",
      cubicBezierEaseInOut: "cubic-bezier(.4, 0, .2, 1)",
      cubicBezierEaseOut: "cubic-bezier(0, 0, .2, 1)",
      cubicBezierEaseIn: "cubic-bezier(.4, 0, 1, 1)",
      borderRadius: "3px",
      borderRadiusSmall: "2px",
      fontSize: "14px",
      fontSizeMini: "12px",
      fontSizeTiny: "12px",
      fontSizeSmall: "14px",
      fontSizeMedium: "14px",
      fontSizeLarge: "15px",
      fontSizeHuge: "16px",
      lineHeight: "1.6",
      heightMini: "16px",
      heightTiny: "22px",
      heightSmall: "28px",
      heightMedium: "34px",
      heightLarge: "40px",
      heightHuge: "46px"
    };
    const {
      fontSize,
      fontFamily,
      lineHeight
    } = _common_default$F;
    var index_cssr_default$5 = c("body", `
 margin: 0;
 font-size: ${fontSize};
 font-family: ${fontFamily};
 line-height: ${lineHeight};
 -webkit-text-size-adjust: 100%;
 -webkit-tap-highlight-color: transparent;
`, [c("input", `
 font-family: inherit;
 font-size: inherit;
 `)]);
    const ssrContextKey = "@css-render/vue3-ssr";
    function createStyleString(id, style) {
      return `<style cssr-id="${id}">
${style}
</style>`;
    }
    function ssrAdapter(id, style, ssrContext) {
      const { styles, ids } = ssrContext;
      if (ids.has(id))
        return;
      if (styles !== null) {
        ids.add(id);
        styles.push(createStyleString(id, style));
      }
    }
    const isBrowser$1 = typeof document !== "undefined";
    function useSsrAdapter() {
      if (isBrowser$1)
        return void 0;
      const context = inject(ssrContextKey, null);
      if (context === null)
        return void 0;
      return {
        adapter: (id, style) => ssrAdapter(id, style, context),
        context
      };
    }
    function useStyle(mountId, style, clsPrefixRef) {
      if (!style) {
        return;
      }
      const ssrAdapter2 = useSsrAdapter();
      const NConfigProvider = inject(configProviderInjectionKey, null);
      const mountStyle = () => {
        const clsPrefix = clsPrefixRef.value;
        style.mount({
          id: clsPrefix === void 0 ? mountId : clsPrefix + mountId,
          head: true,
          anchorMetaName: cssrAnchorMetaName,
          props: {
            bPrefix: clsPrefix ? `.${clsPrefix}-` : void 0
          },
          ssr: ssrAdapter2,
          parent: NConfigProvider?.styleMountTarget
        });
        if (!NConfigProvider?.preflightStyleDisabled) index_cssr_default$5.mount({
          id: "n-global",
          head: true,
          anchorMetaName: cssrAnchorMetaName,
          ssr: ssrAdapter2,
          parent: NConfigProvider?.styleMountTarget
        });
      };
      if (ssrAdapter2) mountStyle();
      else onBeforeMount(mountStyle);
    }
    function normalizeVNode(value, flag = 1) {
      let create = createVNode;
      let isBlock = false;
      if (typeof value === "function") {
        isBlock = true;
        openBlock();
        create = createBlock;
        value = value();
      }
      return isVNode(value) ? isBlock ? createBlock(cloneIfMounted(value)) : cloneIfMounted(value) : Array.isArray(value) ? isBlock ? createElementBlock(Fragment, null, value.map((n) => normalizeVNode(() => n)), -2) : createBaseVNode(Fragment, null, value.slice()) : value == null || typeof value === "boolean" ? create(Comment) : create(Text, null, String(value), flag);
    }
    function cloneIfMounted(child) {
      return child.el === null && child.patchFlag !== -1 || child.memo ? child : cloneVNode(child);
    }
    const normalizeSlots = (slots) => {
      return typeof slots === "function" || Object.prototype.toString.call(slots) === "[object Object]" && !isVNode(slots) ? slots : {
        default: withCtx(() => [normalizeVNode(() => slots)])
      };
    };
    const normalizeClass$1 = (value) => normalizeClass(value) || null;
    function pxfy(value) {
      if (value === void 0 || value === null)
        return void 0;
      if (typeof value === "number")
        return `${value}px`;
      if (value.endsWith("px"))
        return value;
      return `${value}px`;
    }
    const colors = {
      aliceblue: "#F0F8FF",
      antiquewhite: "#FAEBD7",
      aqua: "#0FF",
      aquamarine: "#7FFFD4",
      azure: "#F0FFFF",
      beige: "#F5F5DC",
      bisque: "#FFE4C4",
      black: "#000",
      blanchedalmond: "#FFEBCD",
      blue: "#00F",
      blueviolet: "#8A2BE2",
      brown: "#A52A2A",
      burlywood: "#DEB887",
      cadetblue: "#5F9EA0",
      chartreuse: "#7FFF00",
      chocolate: "#D2691E",
      coral: "#FF7F50",
      cornflowerblue: "#6495ED",
      cornsilk: "#FFF8DC",
      crimson: "#DC143C",
      cyan: "#0FF",
      darkblue: "#00008B",
      darkcyan: "#008B8B",
      darkgoldenrod: "#B8860B",
      darkgray: "#A9A9A9",
      darkgrey: "#A9A9A9",
      darkgreen: "#006400",
      darkkhaki: "#BDB76B",
      darkmagenta: "#8B008B",
      darkolivegreen: "#556B2F",
      darkorange: "#FF8C00",
      darkorchid: "#9932CC",
      darkred: "#8B0000",
      darksalmon: "#E9967A",
      darkseagreen: "#8FBC8F",
      darkslateblue: "#483D8B",
      darkslategray: "#2F4F4F",
      darkslategrey: "#2F4F4F",
      darkturquoise: "#00CED1",
      darkviolet: "#9400D3",
      deeppink: "#FF1493",
      deepskyblue: "#00BFFF",
      dimgray: "#696969",
      dimgrey: "#696969",
      dodgerblue: "#1E90FF",
      firebrick: "#B22222",
      floralwhite: "#FFFAF0",
      forestgreen: "#228B22",
      fuchsia: "#F0F",
      gainsboro: "#DCDCDC",
      ghostwhite: "#F8F8FF",
      gold: "#FFD700",
      goldenrod: "#DAA520",
      gray: "#808080",
      grey: "#808080",
      green: "#008000",
      greenyellow: "#ADFF2F",
      honeydew: "#F0FFF0",
      hotpink: "#FF69B4",
      indianred: "#CD5C5C",
      indigo: "#4B0082",
      ivory: "#FFFFF0",
      khaki: "#F0E68C",
      lavender: "#E6E6FA",
      lavenderblush: "#FFF0F5",
      lawngreen: "#7CFC00",
      lemonchiffon: "#FFFACD",
      lightblue: "#ADD8E6",
      lightcoral: "#F08080",
      lightcyan: "#E0FFFF",
      lightgoldenrodyellow: "#FAFAD2",
      lightgray: "#D3D3D3",
      lightgrey: "#D3D3D3",
      lightgreen: "#90EE90",
      lightpink: "#FFB6C1",
      lightsalmon: "#FFA07A",
      lightseagreen: "#20B2AA",
      lightskyblue: "#87CEFA",
      lightslategray: "#778899",
      lightslategrey: "#778899",
      lightsteelblue: "#B0C4DE",
      lightyellow: "#FFFFE0",
      lime: "#0F0",
      limegreen: "#32CD32",
      linen: "#FAF0E6",
      magenta: "#F0F",
      maroon: "#800000",
      mediumaquamarine: "#66CDAA",
      mediumblue: "#0000CD",
      mediumorchid: "#BA55D3",
      mediumpurple: "#9370DB",
      mediumseagreen: "#3CB371",
      mediumslateblue: "#7B68EE",
      mediumspringgreen: "#00FA9A",
      mediumturquoise: "#48D1CC",
      mediumvioletred: "#C71585",
      midnightblue: "#191970",
      mintcream: "#F5FFFA",
      mistyrose: "#FFE4E1",
      moccasin: "#FFE4B5",
      navajowhite: "#FFDEAD",
      navy: "#000080",
      oldlace: "#FDF5E6",
      olive: "#808000",
      olivedrab: "#6B8E23",
      orange: "#FFA500",
      orangered: "#FF4500",
      orchid: "#DA70D6",
      palegoldenrod: "#EEE8AA",
      palegreen: "#98FB98",
      paleturquoise: "#AFEEEE",
      palevioletred: "#DB7093",
      papayawhip: "#FFEFD5",
      peachpuff: "#FFDAB9",
      peru: "#CD853F",
      pink: "#FFC0CB",
      plum: "#DDA0DD",
      powderblue: "#B0E0E6",
      purple: "#800080",
      rebeccapurple: "#663399",
      red: "#F00",
      rosybrown: "#BC8F8F",
      royalblue: "#4169E1",
      saddlebrown: "#8B4513",
      salmon: "#FA8072",
      sandybrown: "#F4A460",
      seagreen: "#2E8B57",
      seashell: "#FFF5EE",
      sienna: "#A0522D",
      silver: "#C0C0C0",
      skyblue: "#87CEEB",
      slateblue: "#6A5ACD",
      slategray: "#708090",
      slategrey: "#708090",
      snow: "#FFFAFA",
      springgreen: "#00FF7F",
      steelblue: "#4682B4",
      tan: "#D2B48C",
      teal: "#008080",
      thistle: "#D8BFD8",
      tomato: "#FF6347",
      turquoise: "#40E0D0",
      violet: "#EE82EE",
      wheat: "#F5DEB3",
      white: "#FFF",
      whitesmoke: "#F5F5F5",
      yellow: "#FF0",
      yellowgreen: "#9ACD32",
      transparent: "#0000"
    };
    function hsv2rgb(h2, s, v) {
      s /= 100;
      v /= 100;
      let f = (n, k = (n + h2 / 60) % 6) => v - v * s * Math.max(Math.min(k, 4 - k, 1), 0);
      return [f(5) * 255, f(3) * 255, f(1) * 255];
    }
    function hsl2rgb(h2, s, l) {
      s /= 100;
      l /= 100;
      let a = s * Math.min(l, 1 - l);
      let f = (n, k = (n + h2 / 30) % 12) => l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
      return [f(0) * 255, f(8) * 255, f(4) * 255];
    }
    const prefix = "^\\s*";
    const suffix = "\\s*$";
    const percent = "\\s*((\\.\\d+)|(\\d+(\\.\\d*)?))%\\s*";
    const float = "\\s*((\\.\\d+)|(\\d+(\\.\\d*)?))\\s*";
    const hex = "([0-9A-Fa-f])";
    const dhex = "([0-9A-Fa-f]{2})";
    const hslRegex = new RegExp(`${prefix}hsl\\s*\\(${float},${percent},${percent}\\)${suffix}`);
    const hsvRegex = new RegExp(`${prefix}hsv\\s*\\(${float},${percent},${percent}\\)${suffix}`);
    const hslaRegex = new RegExp(`${prefix}hsla\\s*\\(${float},${percent},${percent},${float}\\)${suffix}`);
    const hsvaRegex = new RegExp(`${prefix}hsva\\s*\\(${float},${percent},${percent},${float}\\)${suffix}`);
    const rgbRegex = new RegExp(`${prefix}rgb\\s*\\(${float},${float},${float}\\)${suffix}`);
    const rgbaRegex = new RegExp(`${prefix}rgba\\s*\\(${float},${float},${float},${float}\\)${suffix}`);
    const sHexRegex = new RegExp(`${prefix}#${hex}${hex}${hex}${suffix}`);
    const hexRegex = new RegExp(`${prefix}#${dhex}${dhex}${dhex}${suffix}`);
    const sHexaRegex = new RegExp(`${prefix}#${hex}${hex}${hex}${hex}${suffix}`);
    const hexaRegex = new RegExp(`${prefix}#${dhex}${dhex}${dhex}${dhex}${suffix}`);
    function parseHex(value) {
      return parseInt(value, 16);
    }
    function hsla(color) {
      try {
        let i;
        if (i = hslaRegex.exec(color)) {
          return [
            roundDeg(i[1]),
            roundPercent(i[5]),
            roundPercent(i[9]),
            roundAlpha(i[13])
          ];
        } else if (i = hslRegex.exec(color)) {
          return [roundDeg(i[1]), roundPercent(i[5]), roundPercent(i[9]), 1];
        }
        throw new Error(`[seemly/hsla]: Invalid color value ${color}.`);
      } catch (e) {
        throw e;
      }
    }
    function hsva(color) {
      try {
        let i;
        if (i = hsvaRegex.exec(color)) {
          return [
            roundDeg(i[1]),
            roundPercent(i[5]),
            roundPercent(i[9]),
            roundAlpha(i[13])
          ];
        } else if (i = hsvRegex.exec(color)) {
          return [roundDeg(i[1]), roundPercent(i[5]), roundPercent(i[9]), 1];
        }
        throw new Error(`[seemly/hsva]: Invalid color value ${color}.`);
      } catch (e) {
        throw e;
      }
    }
    function rgba(color) {
      try {
        let i;
        if (i = hexRegex.exec(color)) {
          return [parseHex(i[1]), parseHex(i[2]), parseHex(i[3]), 1];
        } else if (i = rgbRegex.exec(color)) {
          return [roundChannel(i[1]), roundChannel(i[5]), roundChannel(i[9]), 1];
        } else if (i = rgbaRegex.exec(color)) {
          return [
            roundChannel(i[1]),
            roundChannel(i[5]),
            roundChannel(i[9]),
            roundAlpha(i[13])
          ];
        } else if (i = sHexRegex.exec(color)) {
          return [
            parseHex(i[1] + i[1]),
            parseHex(i[2] + i[2]),
            parseHex(i[3] + i[3]),
            1
          ];
        } else if (i = hexaRegex.exec(color)) {
          return [
            parseHex(i[1]),
            parseHex(i[2]),
            parseHex(i[3]),
            roundAlpha(parseHex(i[4]) / 255)
          ];
        } else if (i = sHexaRegex.exec(color)) {
          return [
            parseHex(i[1] + i[1]),
            parseHex(i[2] + i[2]),
            parseHex(i[3] + i[3]),
            roundAlpha(parseHex(i[4] + i[4]) / 255)
          ];
        } else if (color in colors) {
          return rgba(colors[color]);
        } else if (hslRegex.test(color) || hslaRegex.test(color)) {
          const [h2, s, l, a] = hsla(color);
          return [...hsl2rgb(h2, s, l), a];
        } else if (hsvRegex.test(color) || hsvaRegex.test(color)) {
          const [h2, s, v, a] = hsva(color);
          return [...hsv2rgb(h2, s, v), a];
        }
        throw new Error(`[seemly/rgba]: Invalid color value ${color}.`);
      } catch (e) {
        throw e;
      }
    }
    function normalizeAlpha(alphaValue) {
      return alphaValue > 1 ? 1 : alphaValue < 0 ? 0 : alphaValue;
    }
    function stringifyRgba(r, g, b, a) {
      return `rgba(${roundChannel(r)}, ${roundChannel(g)}, ${roundChannel(b)}, ${normalizeAlpha(a)})`;
    }
    function compositeChannel(v1, a1, v2, a2, a) {
      return roundChannel((v1 * a1 * (1 - a2) + v2 * a2) / a);
    }
    function composite(background, overlay2) {
      if (!Array.isArray(background))
        background = rgba(background);
      if (!Array.isArray(overlay2))
        overlay2 = rgba(overlay2);
      const a1 = background[3];
      const a2 = overlay2[3];
      const alpha = roundAlpha(a1 + a2 - a1 * a2);
      return stringifyRgba(compositeChannel(background[0], a1, overlay2[0], a2, alpha), compositeChannel(background[1], a1, overlay2[1], a2, alpha), compositeChannel(background[2], a1, overlay2[2], a2, alpha), alpha);
    }
    function changeColor(base2, options) {
      const [r, g, b, a = 1] = Array.isArray(base2) ? base2 : rgba(base2);
      if (typeof options.alpha === "number") {
        return stringifyRgba(r, g, b, options.alpha);
      }
      return stringifyRgba(r, g, b, a);
    }
    function scaleColor(base2, options) {
      const [r, g, b, a = 1] = Array.isArray(base2) ? base2 : rgba(base2);
      const { lightness = 1, alpha = 1 } = options;
      return toRgbaString([r * lightness, g * lightness, b * lightness, a * alpha]);
    }
    function roundAlpha(value) {
      const v = Math.round(Number(value) * 100) / 100;
      if (v > 1)
        return 1;
      if (v < 0)
        return 0;
      return v;
    }
    function roundDeg(value) {
      const v = Math.round(Number(value));
      if (v >= 360)
        return 0;
      if (v < 0)
        return 0;
      return v;
    }
    function roundChannel(value) {
      const v = Math.round(Number(value));
      if (v > 255)
        return 255;
      if (v < 0)
        return 0;
      return v;
    }
    function roundPercent(value) {
      const v = Math.round(Number(value));
      if (v > 100)
        return 100;
      if (v < 0)
        return 0;
      return v;
    }
    function toRgbaString(base2) {
      const [r, g, b] = base2;
      if (3 in base2) {
        return `rgba(${roundChannel(r)}, ${roundChannel(g)}, ${roundChannel(b)}, ${roundAlpha(base2[3])})`;
      }
      return `rgba(${roundChannel(r)}, ${roundChannel(g)}, ${roundChannel(b)}, 1)`;
    }
    function repeat(count, v) {
      const ret = [];
      for (let i = 0; i < count; ++i) {
        ret.push(v);
      }
      return ret;
    }
    const base$1 = {
      neutralBase: "#000",
      neutralInvertBase: "#fff",
      neutralTextBase: "#fff",
      neutralPopover: "rgb(72, 72, 78)",
      neutralCard: "rgb(24, 24, 28)",
      neutralModal: "rgb(44, 44, 50)",
      neutralBody: "rgb(16, 16, 20)",
      alpha1: "0.9",
      alpha2: "0.82",
      alpha3: "0.52",
      alpha4: "0.38",
      alpha5: "0.28",
      alphaClose: "0.52",
      alphaDisabled: "0.38",
      alphaDisabledInput: "0.06",
      alphaPending: "0.09",
      alphaTablePending: "0.06",
      alphaTableStriped: "0.05",
      alphaPressed: "0.05",
      alphaAvatar: "0.18",
      alphaRail: "0.2",
      alphaProgressRail: "0.12",
      alphaBorder: "0.24",
      alphaDivider: "0.09",
      alphaInput: "0.1",
      alphaAction: "0.06",
      alphaTab: "0.04",
      alphaScrollbar: "0.2",
      alphaScrollbarHover: "0.3",
      alphaCode: "0.12",
      alphaTag: "0.2",
      primaryHover: "#7fe7c4",
      primaryDefault: "#63e2b7",
      primaryActive: "#5acea7",
      primarySuppl: "rgb(42, 148, 125)",
      infoHover: "#8acbec",
      infoDefault: "#70c0e8",
      infoActive: "#66afd3",
      infoSuppl: "rgb(56, 137, 197)",
      errorHover: "#e98b8b",
      errorDefault: "#e88080",
      errorActive: "#e57272",
      errorSuppl: "rgb(208, 58, 82)",
      warningHover: "#f5d599",
      warningDefault: "#f2c97d",
      warningActive: "#e6c260",
      warningSuppl: "rgb(240, 138, 0)",
      successHover: "#7fe7c4",
      successDefault: "#63e2b7",
      successActive: "#5acea7",
      successSuppl: "rgb(42, 148, 125)"
    };
    const baseBackgroundRgb$1 = rgba(base$1.neutralBase);
    const baseInvertBackgroundRgb$1 = rgba(base$1.neutralInvertBase);
    const overlayPrefix$1 = `rgba(${baseInvertBackgroundRgb$1.slice(0, 3).join(", ")}, `;
    function overlay$1(alpha) {
      return `${overlayPrefix$1 + String(alpha)})`;
    }
    function neutral$1(alpha) {
      const overlayRgba = Array.from(baseInvertBackgroundRgb$1);
      overlayRgba[3] = Number(alpha);
      return composite(baseBackgroundRgb$1, overlayRgba);
    }
    const derived$1 = {
      name: "common",
      ..._common_default$F,
      baseColor: base$1.neutralBase,
      primaryColor: base$1.primaryDefault,
      primaryColorHover: base$1.primaryHover,
      primaryColorPressed: base$1.primaryActive,
      primaryColorSuppl: base$1.primarySuppl,
      infoColor: base$1.infoDefault,
      infoColorHover: base$1.infoHover,
      infoColorPressed: base$1.infoActive,
      infoColorSuppl: base$1.infoSuppl,
      successColor: base$1.successDefault,
      successColorHover: base$1.successHover,
      successColorPressed: base$1.successActive,
      successColorSuppl: base$1.successSuppl,
      warningColor: base$1.warningDefault,
      warningColorHover: base$1.warningHover,
      warningColorPressed: base$1.warningActive,
      warningColorSuppl: base$1.warningSuppl,
      errorColor: base$1.errorDefault,
      errorColorHover: base$1.errorHover,
      errorColorPressed: base$1.errorActive,
      errorColorSuppl: base$1.errorSuppl,
      textColorBase: base$1.neutralTextBase,
      textColor1: overlay$1(base$1.alpha1),
      textColor2: overlay$1(base$1.alpha2),
      textColor3: overlay$1(base$1.alpha3),
      textColorDisabled: overlay$1(base$1.alpha4),
      placeholderColor: overlay$1(base$1.alpha4),
      placeholderColorDisabled: overlay$1(base$1.alpha5),
      iconColor: overlay$1(base$1.alpha4),
      iconColorDisabled: overlay$1(base$1.alpha5),
      iconColorHover: overlay$1(Number(base$1.alpha4) * 1.25),
      iconColorPressed: overlay$1(Number(base$1.alpha4) * 0.8),
      opacity1: base$1.alpha1,
      opacity2: base$1.alpha2,
      opacity3: base$1.alpha3,
      opacity4: base$1.alpha4,
      opacity5: base$1.alpha5,
      dividerColor: overlay$1(base$1.alphaDivider),
      borderColor: overlay$1(base$1.alphaBorder),
      closeIconColorHover: overlay$1(Number(base$1.alphaClose)),
      closeIconColor: overlay$1(Number(base$1.alphaClose)),
      closeIconColorPressed: overlay$1(Number(base$1.alphaClose)),
      closeColorHover: "rgba(255, 255, 255, .12)",
      closeColorPressed: "rgba(255, 255, 255, .08)",
      clearColor: overlay$1(base$1.alpha4),
      clearColorHover: scaleColor(overlay$1(base$1.alpha4), {
        alpha: 1.25
      }),
      clearColorPressed: scaleColor(overlay$1(base$1.alpha4), {
        alpha: 0.8
      }),
      scrollbarColor: overlay$1(base$1.alphaScrollbar),
      scrollbarColorHover: overlay$1(base$1.alphaScrollbarHover),
      scrollbarWidth: "5px",
      scrollbarHeight: "5px",
      scrollbarBorderRadius: "5px",
      progressRailColor: overlay$1(base$1.alphaProgressRail),
      railColor: overlay$1(base$1.alphaRail),
      popoverColor: base$1.neutralPopover,
      tableColor: base$1.neutralCard,
      cardColor: base$1.neutralCard,
      modalColor: base$1.neutralModal,
      bodyColor: base$1.neutralBody,
      tagColor: neutral$1(base$1.alphaTag),
      avatarColor: overlay$1(base$1.alphaAvatar),
      invertedColor: base$1.neutralBase,
      inputColor: overlay$1(base$1.alphaInput),
      codeColor: overlay$1(base$1.alphaCode),
      tabColor: overlay$1(base$1.alphaTab),
      actionColor: overlay$1(base$1.alphaAction),
      tableHeaderColor: overlay$1(base$1.alphaAction),
      hoverColor: overlay$1(base$1.alphaPending),
      tableColorHover: overlay$1(base$1.alphaTablePending),
      tableColorStriped: overlay$1(base$1.alphaTableStriped),
      pressedColor: overlay$1(base$1.alphaPressed),
      opacityDisabled: base$1.alphaDisabled,
      inputColorDisabled: overlay$1(base$1.alphaDisabledInput),
      buttonColor2: "rgba(255, 255, 255, .08)",
      buttonColor2Hover: "rgba(255, 255, 255, .12)",
      buttonColor2Pressed: "rgba(255, 255, 255, .08)",
      boxShadow1: "0 1px 2px -2px rgba(0, 0, 0, .24), 0 3px 6px 0 rgba(0, 0, 0, .18), 0 5px 12px 4px rgba(0, 0, 0, .12)",
      boxShadow2: "0 3px 6px -4px rgba(0, 0, 0, .24), 0 6px 12px 0 rgba(0, 0, 0, .16), 0 9px 18px 8px rgba(0, 0, 0, .10)",
      boxShadow3: "0 6px 16px -9px rgba(0, 0, 0, .08), 0 9px 28px 0 rgba(0, 0, 0, .05), 0 12px 48px 16px rgba(0, 0, 0, .03)"
    };
    const base = {
      neutralBase: "#FFF",
      neutralInvertBase: "#000",
      neutralTextBase: "#000",
      neutralPopover: "#fff",
      neutralCard: "#fff",
      neutralModal: "#fff",
      neutralBody: "#fff",
      alpha1: "0.82",
      alpha2: "0.72",
      alpha3: "0.38",
      alpha4: "0.24",
      alpha5: "0.18",
      alphaClose: "0.6",
      alphaDisabled: "0.5",
      alphaAvatar: "0.2",
      alphaProgressRail: ".08",
      alphaInput: "0",
      alphaScrollbar: "0.25",
      alphaScrollbarHover: "0.4",
      primaryHover: "#36ad6a",
      primaryDefault: "#18a058",
      primaryActive: "#0c7a43",
      primarySuppl: "#36ad6a",
      infoHover: "#4098fc",
      infoDefault: "#2080f0",
      infoActive: "#1060c9",
      infoSuppl: "#4098fc",
      errorHover: "#de576d",
      errorDefault: "#d03050",
      errorActive: "#ab1f3f",
      errorSuppl: "#de576d",
      warningHover: "#fcb040",
      warningDefault: "#f0a020",
      warningActive: "#c97c10",
      warningSuppl: "#fcb040",
      successHover: "#36ad6a",
      successDefault: "#18a058",
      successActive: "#0c7a43",
      successSuppl: "#36ad6a"
    };
    const baseBackgroundRgb = rgba(base.neutralBase);
    const baseInvertBackgroundRgb = rgba(base.neutralInvertBase);
    const overlayPrefix = `rgba(${baseInvertBackgroundRgb.slice(0, 3).join(", ")}, `;
    function overlay(alpha) {
      return `${overlayPrefix + String(alpha)})`;
    }
    function neutral(alpha) {
      const overlayRgba = Array.from(baseInvertBackgroundRgb);
      overlayRgba[3] = Number(alpha);
      return composite(baseBackgroundRgb, overlayRgba);
    }
    const derived = {
      name: "common",
      ..._common_default$F,
      baseColor: base.neutralBase,
      primaryColor: base.primaryDefault,
      primaryColorHover: base.primaryHover,
      primaryColorPressed: base.primaryActive,
      primaryColorSuppl: base.primarySuppl,
      infoColor: base.infoDefault,
      infoColorHover: base.infoHover,
      infoColorPressed: base.infoActive,
      infoColorSuppl: base.infoSuppl,
      successColor: base.successDefault,
      successColorHover: base.successHover,
      successColorPressed: base.successActive,
      successColorSuppl: base.successSuppl,
      warningColor: base.warningDefault,
      warningColorHover: base.warningHover,
      warningColorPressed: base.warningActive,
      warningColorSuppl: base.warningSuppl,
      errorColor: base.errorDefault,
      errorColorHover: base.errorHover,
      errorColorPressed: base.errorActive,
      errorColorSuppl: base.errorSuppl,
      textColorBase: base.neutralTextBase,
      textColor1: "rgb(31, 34, 37)",
      textColor2: "rgb(51, 54, 57)",
      textColor3: "rgb(118, 124, 130)",
      textColorDisabled: neutral(base.alpha4),
      placeholderColor: neutral(base.alpha4),
      placeholderColorDisabled: neutral(base.alpha5),
      iconColor: neutral(base.alpha4),
      iconColorHover: scaleColor(neutral(base.alpha4), {
        lightness: 0.75
      }),
      iconColorPressed: scaleColor(neutral(base.alpha4), {
        lightness: 0.9
      }),
      iconColorDisabled: neutral(base.alpha5),
      opacity1: base.alpha1,
      opacity2: base.alpha2,
      opacity3: base.alpha3,
      opacity4: base.alpha4,
      opacity5: base.alpha5,
      dividerColor: "rgb(239, 239, 245)",
      borderColor: "rgb(224, 224, 230)",
      closeIconColor: neutral(Number(base.alphaClose)),
      closeIconColorHover: neutral(Number(base.alphaClose)),
      closeIconColorPressed: neutral(Number(base.alphaClose)),
      closeColorHover: "rgba(0, 0, 0, .09)",
      closeColorPressed: "rgba(0, 0, 0, .13)",
      clearColor: neutral(base.alpha4),
      clearColorHover: scaleColor(neutral(base.alpha4), {
        lightness: 0.75
      }),
      clearColorPressed: scaleColor(neutral(base.alpha4), {
        lightness: 0.9
      }),
      scrollbarColor: overlay(base.alphaScrollbar),
      scrollbarColorHover: overlay(base.alphaScrollbarHover),
      scrollbarWidth: "5px",
      scrollbarHeight: "5px",
      scrollbarBorderRadius: "5px",
      progressRailColor: neutral(base.alphaProgressRail),
      railColor: "rgb(219, 219, 223)",
      popoverColor: base.neutralPopover,
      tableColor: base.neutralCard,
      cardColor: base.neutralCard,
      modalColor: base.neutralModal,
      bodyColor: base.neutralBody,
      tagColor: "#eee",
      avatarColor: neutral(base.alphaAvatar),
      invertedColor: "rgb(0, 20, 40)",
      inputColor: neutral(base.alphaInput),
      codeColor: "rgb(244, 244, 248)",
      tabColor: "rgb(247, 247, 250)",
      actionColor: "rgb(250, 250, 252)",
      tableHeaderColor: "rgb(250, 250, 252)",
      hoverColor: "rgb(243, 243, 245)",
      tableColorHover: "rgba(0, 0, 100, 0.03)",
      tableColorStriped: "rgba(0, 0, 100, 0.02)",
      pressedColor: "rgb(237, 237, 239)",
      opacityDisabled: base.alphaDisabled,
      inputColorDisabled: "rgb(250, 250, 252)",
      buttonColor2: "rgba(46, 51, 56, .05)",
      buttonColor2Hover: "rgba(46, 51, 56, .09)",
      buttonColor2Pressed: "rgba(46, 51, 56, .13)",
      boxShadow1: "0 1px 2px -2px rgba(0, 0, 0, .08), 0 3px 6px 0 rgba(0, 0, 0, .06), 0 5px 12px 4px rgba(0, 0, 0, .04)",
      boxShadow2: "0 3px 6px -4px rgba(0, 0, 0, .12), 0 6px 16px 0 rgba(0, 0, 0, .08), 0 9px 28px 8px rgba(0, 0, 0, .05)",
      boxShadow3: "0 6px 16px -9px rgba(0, 0, 0, .08), 0 9px 28px 0 rgba(0, 0, 0, .05), 0 12px 48px 16px rgba(0, 0, 0, .03)"
    };
    const commonVars = {
      railInsetHorizontalBottom: "auto 2px 4px 2px",
      railInsetHorizontalTop: "4px 2px auto 2px",
      railInsetVerticalRight: "2px 4px 2px auto",
      railInsetVerticalLeft: "2px auto 2px 4px",
      railColor: "transparent"
    };
    function self$1n(vars) {
      const {
        scrollbarColor,
        scrollbarColorHover,
        scrollbarHeight,
        scrollbarWidth,
        scrollbarBorderRadius
      } = vars;
      return {
        ...commonVars,
        height: scrollbarHeight,
        width: scrollbarWidth,
        borderRadius: scrollbarBorderRadius,
        color: scrollbarColor,
        colorHover: scrollbarColorHover
      };
    }
    const scrollbarLight = {
      name: "Scrollbar",
      common: derived,
      self: self$1n
    };
    const scrollbarDark = {
      name: "Scrollbar",
      common: derived$1,
      self: self$1n
    };
    var _common_default$E = {
      iconSizeTiny: "28px",
      iconSizeSmall: "34px",
      iconSizeMedium: "40px",
      iconSizeLarge: "46px",
      iconSizeHuge: "52px"
    };
    function self$1m(vars) {
      const {
        textColorDisabled,
        iconColor,
        textColor2,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        fontSizeHuge
      } = vars;
      return {
        ..._common_default$E,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        fontSizeHuge,
        textColor: textColorDisabled,
        iconColor,
        extraTextColor: textColor2
      };
    }
    const emptyLight = {
      name: "Empty",
      common: derived,
      self: self$1m
    };
    const emptyDark = {
      name: "Empty",
      common: derived$1,
      self: self$1m
    };
    function useThemeClass(componentName, hashRef, cssVarsRef, props) {
      if (!cssVarsRef) throwError("useThemeClass", "cssVarsRef is not passed");
      const NConfigProvider = inject(configProviderInjectionKey, null);
      const mergedThemeHashRef = NConfigProvider?.mergedThemeHashRef;
      const styleMountTarget = NConfigProvider?.styleMountTarget;
      const themeClassRef = /* @__PURE__ */ ref("");
      const ssrAdapter2 = useSsrAdapter();
      let renderCallback;
      const hashClassPrefix = `__${componentName}`;
      const mountStyle = () => {
        let finalThemeHash = hashClassPrefix;
        const hashValue = hashRef ? hashRef.value : void 0;
        const themeHash = mergedThemeHashRef?.value;
        if (themeHash) finalThemeHash += `-${themeHash}`;
        if (hashValue) finalThemeHash += `-${hashValue}`;
        const {
          themeOverrides,
          builtinThemeOverrides
        } = props;
        if (themeOverrides) finalThemeHash += `-${murmur2(JSON.stringify(themeOverrides))}`;
        if (builtinThemeOverrides) finalThemeHash += `-${murmur2(JSON.stringify(builtinThemeOverrides))}`;
        themeClassRef.value = finalThemeHash;
        renderCallback = () => {
          const cssVars = cssVarsRef.value;
          let style = "";
          for (const key in cssVars) style += `${key}: ${cssVars[key]};`;
          c(`.${finalThemeHash}`, style).mount({
            id: finalThemeHash,
            ssr: ssrAdapter2,
            parent: styleMountTarget
          });
          renderCallback = void 0;
        };
      };
      watchEffect(() => {
        mountStyle();
      });
      return {
        themeClass: themeClassRef,
        onRender: () => {
          renderCallback?.();
        }
      };
    }
    function createTheme(theme) {
      return theme;
    }
    function useTheme(resolveId, mountId, style, defaultTheme, props, clsPrefixRef) {
      const ssrAdapter2 = useSsrAdapter();
      const NConfigProvider = inject(configProviderInjectionKey, null);
      if (style) {
        const mountStyle = () => {
          const clsPrefix = clsPrefixRef?.value;
          style.mount({
            id: clsPrefix === void 0 ? mountId : clsPrefix + mountId,
            head: true,
            props: {
              bPrefix: clsPrefix ? `.${clsPrefix}-` : void 0
            },
            anchorMetaName: cssrAnchorMetaName,
            ssr: ssrAdapter2,
            parent: NConfigProvider?.styleMountTarget
          });
          if (!NConfigProvider?.preflightStyleDisabled) index_cssr_default$5.mount({
            id: "n-global",
            head: true,
            anchorMetaName: cssrAnchorMetaName,
            ssr: ssrAdapter2,
            parent: NConfigProvider?.styleMountTarget
          });
        };
        if (ssrAdapter2) mountStyle();
        else onBeforeMount(mountStyle);
      }
      return computed(() => {
        const {
          theme: {
            common: selfCommon,
            self: self2,
            peers = {}
          } = {},
          themeOverrides: selfOverrides = {},
          builtinThemeOverrides: builtinOverrides = {}
        } = props;
        const {
          common: selfCommonOverrides,
          peers: peersOverrides
        } = selfOverrides;
        const {
          common: globalCommon = void 0,
          [resolveId]: {
            common: globalSelfCommon = void 0,
            self: globalSelf = void 0,
            peers: globalPeers = {}
          } = {}
        } = NConfigProvider?.mergedThemeRef.value || {};
        const {
          common: globalCommonOverrides = void 0,
          [resolveId]: globalSelfOverrides = {}
        } = NConfigProvider?.mergedThemeOverridesRef.value || {};
        const {
          common: globalSelfCommonOverrides,
          peers: globalPeersOverrides = {}
        } = globalSelfOverrides;
        const mergedCommon = merge({}, selfCommon || globalSelfCommon || globalCommon || defaultTheme.common, globalCommonOverrides, globalSelfCommonOverrides, selfCommonOverrides);
        return {
          common: mergedCommon,
          self: merge((self2 || globalSelf || defaultTheme.self)?.(mergedCommon), builtinOverrides, globalSelfOverrides, selfOverrides),
          peers: merge({}, defaultTheme.peers, globalPeers, peers),
          peerOverrides: merge({}, builtinOverrides.peers, globalPeersOverrides, peersOverrides)
        };
      });
    }
    useTheme.props = {
      theme: Object,
      themeOverrides: Object,
      builtinThemeOverrides: Object
    };
    var _common_default$D = {
      height: "calc(var(--n-option-height) * 7.6)",
      paddingTiny: "4px 0",
      paddingSmall: "4px 0",
      paddingMedium: "4px 0",
      paddingLarge: "4px 0",
      paddingHuge: "4px 0",
      optionPaddingTiny: "0 12px",
      optionPaddingSmall: "0 12px",
      optionPaddingMedium: "0 12px",
      optionPaddingLarge: "0 12px",
      optionPaddingHuge: "0 12px",
      loadingSize: "18px"
    };
    function self$1l(vars) {
      const {
        borderRadius,
        popoverColor,
        textColor3,
        dividerColor,
        textColor2,
        primaryColorPressed,
        textColorDisabled,
        primaryColor,
        opacityDisabled,
        hoverColor,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        fontSizeHuge,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        heightHuge
      } = vars;
      return {
        ..._common_default$D,
        optionFontSizeTiny: fontSizeTiny,
        optionFontSizeSmall: fontSizeSmall,
        optionFontSizeMedium: fontSizeMedium,
        optionFontSizeLarge: fontSizeLarge,
        optionFontSizeHuge: fontSizeHuge,
        optionHeightTiny: heightTiny,
        optionHeightSmall: heightSmall,
        optionHeightMedium: heightMedium,
        optionHeightLarge: heightLarge,
        optionHeightHuge: heightHuge,
        borderRadius,
        color: popoverColor,
        groupHeaderTextColor: textColor3,
        actionDividerColor: dividerColor,
        optionTextColor: textColor2,
        optionTextColorPressed: primaryColorPressed,
        optionTextColorDisabled: textColorDisabled,
        optionTextColorActive: primaryColor,
        optionOpacityDisabled: opacityDisabled,
        optionCheckColor: primaryColor,
        optionColorPending: hoverColor,
        optionColorActive: "rgba(0, 0, 0, 0)",
        optionColorActivePending: hoverColor,
        actionTextColor: textColor2,
        loadingColor: primaryColor
      };
    }
    const internalSelectMenuLight = createTheme({
      name: "InternalSelectMenu",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight,
        Empty: emptyLight
      },
      self: self$1l
    });
    const internalSelectMenuDark = {
      name: "InternalSelectMenu",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark,
        Empty: emptyDark
      },
      self: self$1l
    };
    var _common_default$C = {
      space: "6px",
      spaceArrow: "10px",
      arrowOffset: "10px",
      arrowOffsetVertical: "10px",
      arrowHeight: "6px",
      padding: "8px 14px"
    };
    function self$1k(vars) {
      const {
        boxShadow2,
        popoverColor,
        textColor2,
        borderRadius,
        fontSize: fontSize2,
        dividerColor
      } = vars;
      return {
        ..._common_default$C,
        fontSize: fontSize2,
        borderRadius,
        color: popoverColor,
        dividerColor,
        textColor: textColor2,
        boxShadow: boxShadow2
      };
    }
    const popoverLight = createTheme({
      name: "Popover",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight
      },
      self: self$1k
    });
    const popoverDark = {
      name: "Popover",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark
      },
      self: self$1k
    };
    function useMemo(getterOrOptions) {
      const computedValueRef = computed(getterOrOptions);
      const valueRef = /* @__PURE__ */ ref(computedValueRef.value);
      watch(computedValueRef, (value) => {
        valueRef.value = value;
      });
      if (typeof getterOrOptions === "function") {
        return valueRef;
      } else {
        return {
          __v_isRef: true,
          get value() {
            return valueRef.value;
          },
          set value(v) {
            getterOrOptions.set(v);
          }
        };
      }
    }
    function isMounted() {
      const isMounted2 = /* @__PURE__ */ ref(false);
      onMounted(() => {
        isMounted2.value = true;
      });
      return /* @__PURE__ */ readonly(isMounted2);
    }
    function call(funcs, ...args) {
      if (Array.isArray(funcs)) funcs.forEach((func) => call(func, ...args));
      else return funcs(...args);
    }
    const pureNumberRegex = /^(\d|\.)+$/;
    const numberRegex = /(\d|\.)+/;
    function formatLength(length, {
      c: c2 = 1,
      offset = 0,
      attachPx = true
    } = {}) {
      if (typeof length === "number") {
        const result = (length + offset) * c2;
        if (result === 0) return "0";
        return `${result}px`;
      } else if (typeof length === "string") {
        if (pureNumberRegex.test(length)) {
          const result = (Number(length) + offset) * c2;
          if (attachPx) {
            if (result === 0) return "0";
            return `${result}px`;
          } else return `${result}`;
        } else {
          const result = numberRegex.exec(length);
          if (!result) return length;
          return length.replace(numberRegex, String((Number(result[0]) + offset) * c2));
        }
      }
      return length;
    }
    function ensureValidVNode(vnodes) {
      return vnodes.some((child) => {
        if (!isVNode(child)) return true;
        if (child.type === Comment) return false;
        if (child.type === Fragment && !ensureValidVNode(child.children)) return false;
        return true;
      }) ? vnodes : null;
    }
    function resolveWrappedSlot(slot, wrapper) {
      return wrapper(slot && ensureValidVNode(slot()) || null);
    }
    function isSlotEmpty(slot) {
      return !(slot && ensureValidVNode(slot()));
    }
    function useRtl(mountId, rtlStateRef, clsPrefixRef) {
      if (!rtlStateRef) return void 0;
      const ssrAdapter2 = useSsrAdapter();
      const componentRtlStateRef = computed(() => {
        const {
          value: rtlState
        } = rtlStateRef;
        if (!rtlState) return;
        const componentRtlState = rtlState[mountId];
        if (!componentRtlState) return;
        return componentRtlState;
      });
      const NConfigProvider = inject(configProviderInjectionKey, null);
      const mountStyle = () => {
        watchEffect(() => {
          const {
            value: clsPrefix
          } = clsPrefixRef;
          const id = `${clsPrefix}${mountId}Rtl`;
          if (exists(id, ssrAdapter2)) return;
          const {
            value: componentRtlState
          } = componentRtlStateRef;
          if (!componentRtlState) return;
          componentRtlState.style.mount({
            id,
            head: true,
            anchorMetaName: cssrAnchorMetaName,
            props: {
              bPrefix: clsPrefix ? `.${clsPrefix}-` : void 0
            },
            ssr: ssrAdapter2,
            parent: NConfigProvider?.styleMountTarget
          });
        });
      };
      if (ssrAdapter2) mountStyle();
      else onBeforeMount(mountStyle);
      return componentRtlStateRef;
    }
    var _common_default$B = {
      closeIconSizeTiny: "12px",
      closeIconSizeSmall: "12px",
      closeIconSizeMedium: "14px",
      closeIconSizeLarge: "14px",
      closeSizeTiny: "16px",
      closeSizeSmall: "16px",
      closeSizeMedium: "18px",
      closeSizeLarge: "18px",
      padding: "0 7px",
      closeMargin: "0 0 0 4px"
    };
    const tagDark = {
      name: "Tag",
      common: derived$1,
      self(vars) {
        const {
          textColor2,
          primaryColorHover,
          primaryColorPressed,
          primaryColor,
          infoColor,
          successColor,
          warningColor,
          errorColor,
          baseColor,
          borderColor,
          tagColor,
          opacityDisabled,
          closeIconColor,
          closeIconColorHover,
          closeIconColorPressed,
          closeColorHover,
          closeColorPressed,
          borderRadiusSmall: borderRadius,
          fontSizeMini,
          fontSizeTiny,
          fontSizeSmall,
          fontSizeMedium,
          heightMini,
          heightTiny,
          heightSmall,
          heightMedium,
          buttonColor2Hover,
          buttonColor2Pressed,
          fontWeightStrong
        } = vars;
        return {
          ..._common_default$B,
          closeBorderRadius: borderRadius,
          heightTiny: heightMini,
          heightSmall: heightTiny,
          heightMedium: heightSmall,
          heightLarge: heightMedium,
          borderRadius,
          opacityDisabled,
          fontSizeTiny: fontSizeMini,
          fontSizeSmall: fontSizeTiny,
          fontSizeMedium: fontSizeSmall,
          fontSizeLarge: fontSizeMedium,
          fontWeightStrong,
          textColorCheckable: textColor2,
          textColorHoverCheckable: textColor2,
          textColorPressedCheckable: textColor2,
          textColorChecked: baseColor,
          colorCheckable: "#0000",
          colorHoverCheckable: buttonColor2Hover,
          colorPressedCheckable: buttonColor2Pressed,
          colorChecked: primaryColor,
          colorCheckedHover: primaryColorHover,
          colorCheckedPressed: primaryColorPressed,
          border: `1px solid ${borderColor}`,
          textColor: textColor2,
          color: tagColor,
          colorBordered: "#0000",
          closeIconColor,
          closeIconColorHover,
          closeIconColorPressed,
          closeColorHover,
          closeColorPressed,
          borderPrimary: `1px solid ${changeColor(primaryColor, {
            alpha: 0.3
          })}`,
          textColorPrimary: primaryColor,
          colorPrimary: changeColor(primaryColor, {
            alpha: 0.16
          }),
          colorBorderedPrimary: "#0000",
          closeIconColorPrimary: scaleColor(primaryColor, {
            lightness: 0.7
          }),
          closeIconColorHoverPrimary: scaleColor(primaryColor, {
            lightness: 0.7
          }),
          closeIconColorPressedPrimary: scaleColor(primaryColor, {
            lightness: 0.7
          }),
          closeColorHoverPrimary: changeColor(primaryColor, {
            alpha: 0.16
          }),
          closeColorPressedPrimary: changeColor(primaryColor, {
            alpha: 0.12
          }),
          borderInfo: `1px solid ${changeColor(infoColor, {
            alpha: 0.3
          })}`,
          textColorInfo: infoColor,
          colorInfo: changeColor(infoColor, {
            alpha: 0.16
          }),
          colorBorderedInfo: "#0000",
          closeIconColorInfo: scaleColor(infoColor, {
            alpha: 0.7
          }),
          closeIconColorHoverInfo: scaleColor(infoColor, {
            alpha: 0.7
          }),
          closeIconColorPressedInfo: scaleColor(infoColor, {
            alpha: 0.7
          }),
          closeColorHoverInfo: changeColor(infoColor, {
            alpha: 0.16
          }),
          closeColorPressedInfo: changeColor(infoColor, {
            alpha: 0.12
          }),
          borderSuccess: `1px solid ${changeColor(successColor, {
            alpha: 0.3
          })}`,
          textColorSuccess: successColor,
          colorSuccess: changeColor(successColor, {
            alpha: 0.16
          }),
          colorBorderedSuccess: "#0000",
          closeIconColorSuccess: scaleColor(successColor, {
            alpha: 0.7
          }),
          closeIconColorHoverSuccess: scaleColor(successColor, {
            alpha: 0.7
          }),
          closeIconColorPressedSuccess: scaleColor(successColor, {
            alpha: 0.7
          }),
          closeColorHoverSuccess: changeColor(successColor, {
            alpha: 0.16
          }),
          closeColorPressedSuccess: changeColor(successColor, {
            alpha: 0.12
          }),
          borderWarning: `1px solid ${changeColor(warningColor, {
            alpha: 0.3
          })}`,
          textColorWarning: warningColor,
          colorWarning: changeColor(warningColor, {
            alpha: 0.16
          }),
          colorBorderedWarning: "#0000",
          closeIconColorWarning: scaleColor(warningColor, {
            alpha: 0.7
          }),
          closeIconColorHoverWarning: scaleColor(warningColor, {
            alpha: 0.7
          }),
          closeIconColorPressedWarning: scaleColor(warningColor, {
            alpha: 0.7
          }),
          closeColorHoverWarning: changeColor(warningColor, {
            alpha: 0.16
          }),
          closeColorPressedWarning: changeColor(warningColor, {
            alpha: 0.11
          }),
          borderError: `1px solid ${changeColor(errorColor, {
            alpha: 0.3
          })}`,
          textColorError: errorColor,
          colorError: changeColor(errorColor, {
            alpha: 0.16
          }),
          colorBorderedError: "#0000",
          closeIconColorError: scaleColor(errorColor, {
            alpha: 0.7
          }),
          closeIconColorHoverError: scaleColor(errorColor, {
            alpha: 0.7
          }),
          closeIconColorPressedError: scaleColor(errorColor, {
            alpha: 0.7
          }),
          closeColorHoverError: changeColor(errorColor, {
            alpha: 0.16
          }),
          closeColorPressedError: changeColor(errorColor, {
            alpha: 0.12
          })
        };
      }
    };
    function color2Class(color) {
      return color.replace(/#|\(|\)|,|\s|\./g, "_");
    }
    function self$1j(vars) {
      const {
        textColor2,
        primaryColorHover,
        primaryColorPressed,
        primaryColor,
        infoColor,
        successColor,
        warningColor,
        errorColor,
        baseColor,
        borderColor,
        opacityDisabled,
        tagColor,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        borderRadiusSmall: borderRadius,
        fontSizeMini,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        heightMini,
        heightTiny,
        heightSmall,
        heightMedium,
        closeColorHover,
        closeColorPressed,
        buttonColor2Hover,
        buttonColor2Pressed,
        fontWeightStrong
      } = vars;
      return {
        ..._common_default$B,
        closeBorderRadius: borderRadius,
        heightTiny: heightMini,
        heightSmall: heightTiny,
        heightMedium: heightSmall,
        heightLarge: heightMedium,
        borderRadius,
        opacityDisabled,
        fontSizeTiny: fontSizeMini,
        fontSizeSmall: fontSizeTiny,
        fontSizeMedium: fontSizeSmall,
        fontSizeLarge: fontSizeMedium,
        fontWeightStrong,
        textColorCheckable: textColor2,
        textColorHoverCheckable: textColor2,
        textColorPressedCheckable: textColor2,
        textColorChecked: baseColor,
        colorCheckable: "#0000",
        colorHoverCheckable: buttonColor2Hover,
        colorPressedCheckable: buttonColor2Pressed,
        colorChecked: primaryColor,
        colorCheckedHover: primaryColorHover,
        colorCheckedPressed: primaryColorPressed,
        border: `1px solid ${borderColor}`,
        textColor: textColor2,
        color: tagColor,
        colorBordered: "rgb(250, 250, 252)",
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeColorHover,
        closeColorPressed,
        borderPrimary: `1px solid ${changeColor(primaryColor, {
          alpha: 0.3
        })}`,
        textColorPrimary: primaryColor,
        colorPrimary: changeColor(primaryColor, {
          alpha: 0.12
        }),
        colorBorderedPrimary: changeColor(primaryColor, {
          alpha: 0.1
        }),
        closeIconColorPrimary: primaryColor,
        closeIconColorHoverPrimary: primaryColor,
        closeIconColorPressedPrimary: primaryColor,
        closeColorHoverPrimary: changeColor(primaryColor, {
          alpha: 0.12
        }),
        closeColorPressedPrimary: changeColor(primaryColor, {
          alpha: 0.18
        }),
        borderInfo: `1px solid ${changeColor(infoColor, {
          alpha: 0.3
        })}`,
        textColorInfo: infoColor,
        colorInfo: changeColor(infoColor, {
          alpha: 0.12
        }),
        colorBorderedInfo: changeColor(infoColor, {
          alpha: 0.1
        }),
        closeIconColorInfo: infoColor,
        closeIconColorHoverInfo: infoColor,
        closeIconColorPressedInfo: infoColor,
        closeColorHoverInfo: changeColor(infoColor, {
          alpha: 0.12
        }),
        closeColorPressedInfo: changeColor(infoColor, {
          alpha: 0.18
        }),
        borderSuccess: `1px solid ${changeColor(successColor, {
          alpha: 0.3
        })}`,
        textColorSuccess: successColor,
        colorSuccess: changeColor(successColor, {
          alpha: 0.12
        }),
        colorBorderedSuccess: changeColor(successColor, {
          alpha: 0.1
        }),
        closeIconColorSuccess: successColor,
        closeIconColorHoverSuccess: successColor,
        closeIconColorPressedSuccess: successColor,
        closeColorHoverSuccess: changeColor(successColor, {
          alpha: 0.12
        }),
        closeColorPressedSuccess: changeColor(successColor, {
          alpha: 0.18
        }),
        borderWarning: `1px solid ${changeColor(warningColor, {
          alpha: 0.35
        })}`,
        textColorWarning: warningColor,
        colorWarning: changeColor(warningColor, {
          alpha: 0.15
        }),
        colorBorderedWarning: changeColor(warningColor, {
          alpha: 0.12
        }),
        closeIconColorWarning: warningColor,
        closeIconColorHoverWarning: warningColor,
        closeIconColorPressedWarning: warningColor,
        closeColorHoverWarning: changeColor(warningColor, {
          alpha: 0.12
        }),
        closeColorPressedWarning: changeColor(warningColor, {
          alpha: 0.18
        }),
        borderError: `1px solid ${changeColor(errorColor, {
          alpha: 0.23
        })}`,
        textColorError: errorColor,
        colorError: changeColor(errorColor, {
          alpha: 0.1
        }),
        colorBorderedError: changeColor(errorColor, {
          alpha: 0.08
        }),
        closeIconColorError: errorColor,
        closeIconColorHoverError: errorColor,
        closeIconColorPressedError: errorColor,
        closeColorHoverError: changeColor(errorColor, {
          alpha: 0.12
        }),
        closeColorPressedError: changeColor(errorColor, {
          alpha: 0.18
        })
      };
    }
    const tagLight = {
      name: "Tag",
      common: derived,
      self: self$1j
    };
    var _common_default$A = {
      paddingSingle: "0 26px 0 12px",
      paddingMultiple: "3px 26px 0 12px",
      clearSize: "16px",
      arrowSize: "16px"
    };
    const internalSelectionDark = {
      name: "InternalSelection",
      common: derived$1,
      peers: {
        Popover: popoverDark
      },
      self(vars) {
        const {
          borderRadius,
          textColor2,
          textColorDisabled,
          inputColor,
          inputColorDisabled,
          primaryColor,
          primaryColorHover,
          warningColor,
          warningColorHover,
          errorColor,
          errorColorHover,
          iconColor,
          iconColorDisabled,
          clearColor,
          clearColorHover,
          clearColorPressed,
          placeholderColor,
          placeholderColorDisabled,
          fontSizeTiny,
          fontSizeSmall,
          fontSizeMedium,
          fontSizeLarge,
          heightTiny,
          heightSmall,
          heightMedium,
          heightLarge,
          fontWeight
        } = vars;
        return {
          ..._common_default$A,
          fontWeight,
          fontSizeTiny,
          fontSizeSmall,
          fontSizeMedium,
          fontSizeLarge,
          heightTiny,
          heightSmall,
          heightMedium,
          heightLarge,
          borderRadius,
          textColor: textColor2,
          textColorDisabled,
          placeholderColor,
          placeholderColorDisabled,
          color: inputColor,
          colorDisabled: inputColorDisabled,
          colorActive: changeColor(primaryColor, {
            alpha: 0.1
          }),
          border: "1px solid #0000",
          borderHover: `1px solid ${primaryColorHover}`,
          borderActive: `1px solid ${primaryColor}`,
          borderFocus: `1px solid ${primaryColorHover}`,
          boxShadowHover: "none",
          boxShadowActive: `0 0 8px 0 ${changeColor(primaryColor, {
            alpha: 0.4
          })}`,
          boxShadowFocus: `0 0 8px 0 ${changeColor(primaryColor, {
            alpha: 0.4
          })}`,
          caretColor: primaryColor,
          arrowColor: iconColor,
          arrowColorDisabled: iconColorDisabled,
          loadingColor: primaryColor,
          borderWarning: `1px solid ${warningColor}`,
          borderHoverWarning: `1px solid ${warningColorHover}`,
          borderActiveWarning: `1px solid ${warningColor}`,
          borderFocusWarning: `1px solid ${warningColorHover}`,
          boxShadowHoverWarning: "none",
          boxShadowActiveWarning: `0 0 8px 0 ${changeColor(warningColor, {
            alpha: 0.4
          })}`,
          boxShadowFocusWarning: `0 0 8px 0 ${changeColor(warningColor, {
            alpha: 0.4
          })}`,
          colorActiveWarning: changeColor(warningColor, {
            alpha: 0.1
          }),
          caretColorWarning: warningColor,
          borderError: `1px solid ${errorColor}`,
          borderHoverError: `1px solid ${errorColorHover}`,
          borderActiveError: `1px solid ${errorColor}`,
          borderFocusError: `1px solid ${errorColorHover}`,
          boxShadowHoverError: "none",
          boxShadowActiveError: `0 0 8px 0 ${changeColor(errorColor, {
            alpha: 0.4
          })}`,
          boxShadowFocusError: `0 0 8px 0 ${changeColor(errorColor, {
            alpha: 0.4
          })}`,
          colorActiveError: changeColor(errorColor, {
            alpha: 0.1
          }),
          caretColorError: errorColor,
          clearColor,
          clearColorHover,
          clearColorPressed
        };
      }
    };
    var _common_default$z = {
      iconMargin: "11px 8px 0 12px",
      iconMarginRtl: "11px 12px 0 8px",
      iconSize: "24px",
      closeIconSize: "16px",
      closeSize: "20px",
      closeMargin: "13px 14px 0 0",
      closeMarginRtl: "13px 0 0 14px",
      padding: "13px"
    };
    const alertDark = {
      name: "Alert",
      common: derived$1,
      self(vars) {
        const {
          lineHeight: lineHeight2,
          borderRadius,
          fontWeightStrong,
          dividerColor,
          inputColor,
          textColor1,
          textColor2,
          closeColorHover,
          closeColorPressed,
          closeIconColor,
          closeIconColorHover,
          closeIconColorPressed,
          infoColorSuppl,
          successColorSuppl,
          warningColorSuppl,
          errorColorSuppl,
          fontSize: fontSize2
        } = vars;
        return {
          ..._common_default$z,
          fontSize: fontSize2,
          lineHeight: lineHeight2,
          titleFontWeight: fontWeightStrong,
          borderRadius,
          border: `1px solid ${dividerColor}`,
          color: inputColor,
          titleTextColor: textColor1,
          iconColor: textColor2,
          contentTextColor: textColor2,
          closeBorderRadius: borderRadius,
          closeColorHover,
          closeColorPressed,
          closeIconColor,
          closeIconColorHover,
          closeIconColorPressed,
          borderInfo: `1px solid ${changeColor(infoColorSuppl, {
            alpha: 0.35
          })}`,
          colorInfo: changeColor(infoColorSuppl, {
            alpha: 0.25
          }),
          titleTextColorInfo: textColor1,
          iconColorInfo: infoColorSuppl,
          contentTextColorInfo: textColor2,
          closeColorHoverInfo: closeColorHover,
          closeColorPressedInfo: closeColorPressed,
          closeIconColorInfo: closeIconColor,
          closeIconColorHoverInfo: closeIconColorHover,
          closeIconColorPressedInfo: closeIconColorPressed,
          borderSuccess: `1px solid ${changeColor(successColorSuppl, {
            alpha: 0.35
          })}`,
          colorSuccess: changeColor(successColorSuppl, {
            alpha: 0.25
          }),
          titleTextColorSuccess: textColor1,
          iconColorSuccess: successColorSuppl,
          contentTextColorSuccess: textColor2,
          closeColorHoverSuccess: closeColorHover,
          closeColorPressedSuccess: closeColorPressed,
          closeIconColorSuccess: closeIconColor,
          closeIconColorHoverSuccess: closeIconColorHover,
          closeIconColorPressedSuccess: closeIconColorPressed,
          borderWarning: `1px solid ${changeColor(warningColorSuppl, {
            alpha: 0.35
          })}`,
          colorWarning: changeColor(warningColorSuppl, {
            alpha: 0.25
          }),
          titleTextColorWarning: textColor1,
          iconColorWarning: warningColorSuppl,
          contentTextColorWarning: textColor2,
          closeColorHoverWarning: closeColorHover,
          closeColorPressedWarning: closeColorPressed,
          closeIconColorWarning: closeIconColor,
          closeIconColorHoverWarning: closeIconColorHover,
          closeIconColorPressedWarning: closeIconColorPressed,
          borderError: `1px solid ${changeColor(errorColorSuppl, {
            alpha: 0.35
          })}`,
          colorError: changeColor(errorColorSuppl, {
            alpha: 0.25
          }),
          titleTextColorError: textColor1,
          iconColorError: errorColorSuppl,
          contentTextColorError: textColor2,
          closeColorHoverError: closeColorHover,
          closeColorPressedError: closeColorPressed,
          closeIconColorError: closeIconColor,
          closeIconColorHoverError: closeIconColorHover,
          closeIconColorPressedError: closeIconColorPressed
        };
      }
    };
    var FadeInExpandTransition_default = /* @__PURE__ */ defineComponent({
      name: "FadeInExpandTransition",
      props: {
        appear: Boolean,
        group: Boolean,
        mode: String,
        onLeave: Function,
        onAfterLeave: Function,
        onAfterEnter: Function,
        width: Boolean,
        reverse: Boolean
      },
      setup(props, {
        slots
      }) {
        function handleBeforeLeave(el) {
          if (props.width) el.style.maxWidth = `${el.offsetWidth}px`;
          else el.style.maxHeight = `${el.offsetHeight}px`;
          el.offsetWidth;
        }
        function handleLeave(el) {
          if (props.width) el.style.maxWidth = "0";
          else el.style.maxHeight = "0";
          el.offsetWidth;
          const {
            onLeave
          } = props;
          if (onLeave) onLeave();
        }
        function handleAfterLeave(el) {
          if (props.width) el.style.maxWidth = "";
          else el.style.maxHeight = "";
          const {
            onAfterLeave
          } = props;
          if (onAfterLeave) onAfterLeave();
        }
        function handleEnter(el) {
          el.style.transition = "none";
          if (props.width) {
            const memorizedWidth = el.offsetWidth;
            el.style.maxWidth = "0";
            el.offsetWidth;
            el.style.transition = "";
            el.style.maxWidth = `${memorizedWidth}px`;
          } else if (props.reverse) {
            el.style.maxHeight = `${el.offsetHeight}px`;
            el.offsetHeight;
            el.style.transition = "";
            el.style.maxHeight = "0";
          } else {
            const memorizedHeight = el.offsetHeight;
            el.style.maxHeight = "0";
            el.offsetWidth;
            el.style.transition = "";
            el.style.maxHeight = `${memorizedHeight}px`;
          }
          el.offsetWidth;
        }
        function handleAfterEnter(el) {
          if (props.width) el.style.maxWidth = "";
          else if (!props.reverse) el.style.maxHeight = "";
          props.onAfterEnter?.();
        }
        return () => {
          const {
            group,
            width,
            appear,
            mode
          } = props;
          const type = group ? TransitionGroup : Transition;
          const resolvedProps = {
            name: width ? "fade-in-width-expand-transition" : "fade-in-height-expand-transition",
            appear,
            onEnter: handleEnter,
            onAfterEnter: handleAfterEnter,
            onBeforeLeave: handleBeforeLeave,
            onLeave: handleLeave,
            onAfterLeave: handleAfterLeave
          };
          if (!group) resolvedProps.mode = mode;
          return h(type, resolvedProps, slots);
        };
      }
    });
    function self$1i(vars) {
      const {
        lineHeight: lineHeight2,
        borderRadius,
        fontWeightStrong,
        baseColor,
        dividerColor,
        actionColor,
        textColor1,
        textColor2,
        closeColorHover,
        closeColorPressed,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        infoColor,
        successColor,
        warningColor,
        errorColor,
        fontSize: fontSize2
      } = vars;
      return {
        ..._common_default$z,
        fontSize: fontSize2,
        lineHeight: lineHeight2,
        titleFontWeight: fontWeightStrong,
        borderRadius,
        border: `1px solid ${dividerColor}`,
        color: actionColor,
        titleTextColor: textColor1,
        iconColor: textColor2,
        contentTextColor: textColor2,
        closeBorderRadius: borderRadius,
        closeColorHover,
        closeColorPressed,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        borderInfo: `1px solid ${composite(baseColor, changeColor(infoColor, {
          alpha: 0.25
        }))}`,
        colorInfo: composite(baseColor, changeColor(infoColor, {
          alpha: 0.08
        })),
        titleTextColorInfo: textColor1,
        iconColorInfo: infoColor,
        contentTextColorInfo: textColor2,
        closeColorHoverInfo: closeColorHover,
        closeColorPressedInfo: closeColorPressed,
        closeIconColorInfo: closeIconColor,
        closeIconColorHoverInfo: closeIconColorHover,
        closeIconColorPressedInfo: closeIconColorPressed,
        borderSuccess: `1px solid ${composite(baseColor, changeColor(successColor, {
          alpha: 0.25
        }))}`,
        colorSuccess: composite(baseColor, changeColor(successColor, {
          alpha: 0.08
        })),
        titleTextColorSuccess: textColor1,
        iconColorSuccess: successColor,
        contentTextColorSuccess: textColor2,
        closeColorHoverSuccess: closeColorHover,
        closeColorPressedSuccess: closeColorPressed,
        closeIconColorSuccess: closeIconColor,
        closeIconColorHoverSuccess: closeIconColorHover,
        closeIconColorPressedSuccess: closeIconColorPressed,
        borderWarning: `1px solid ${composite(baseColor, changeColor(warningColor, {
          alpha: 0.33
        }))}`,
        colorWarning: composite(baseColor, changeColor(warningColor, {
          alpha: 0.08
        })),
        titleTextColorWarning: textColor1,
        iconColorWarning: warningColor,
        contentTextColorWarning: textColor2,
        closeColorHoverWarning: closeColorHover,
        closeColorPressedWarning: closeColorPressed,
        closeIconColorWarning: closeIconColor,
        closeIconColorHoverWarning: closeIconColorHover,
        closeIconColorPressedWarning: closeIconColorPressed,
        borderError: `1px solid ${composite(baseColor, changeColor(errorColor, {
          alpha: 0.25
        }))}`,
        colorError: composite(baseColor, changeColor(errorColor, {
          alpha: 0.08
        })),
        titleTextColorError: textColor1,
        iconColorError: errorColor,
        contentTextColorError: textColor2,
        closeColorHoverError: closeColorHover,
        closeColorPressedError: closeColorPressed,
        closeIconColorError: closeIconColor,
        closeIconColorHoverError: closeIconColorHover,
        closeIconColorPressedError: closeIconColorPressed
      };
    }
    const alertLight = {
      name: "Alert",
      common: derived,
      self: self$1i
    };
    var _common_default$y = {
      linkFontSize: "13px",
      linkPadding: "0 0 0 16px",
      railWidth: "4px"
    };
    function self$1h(vars) {
      const {
        borderRadius,
        railColor,
        primaryColor,
        primaryColorHover,
        primaryColorPressed,
        textColor2
      } = vars;
      return {
        ..._common_default$y,
        borderRadius,
        railColor,
        railColorActive: primaryColor,
        linkColor: changeColor(primaryColor, {
          alpha: 0.15
        }),
        linkTextColor: textColor2,
        linkTextColorHover: primaryColorHover,
        linkTextColorPressed: primaryColorPressed,
        linkTextColorActive: primaryColor
      };
    }
    const anchorLight = {
      name: "Anchor",
      common: derived,
      self: self$1h
    };
    const anchorDark = {
      name: "Anchor",
      common: derived$1,
      self: self$1h
    };
    var _common_default$x = {
      paddingTiny: "0 8px",
      paddingSmall: "0 10px",
      paddingMedium: "0 12px",
      paddingLarge: "0 14px",
      clearSize: "16px"
    };
    function self$1g(vars) {
      const {
        textColor2,
        textColor3,
        textColorDisabled,
        primaryColor,
        primaryColorHover,
        inputColor,
        inputColorDisabled,
        warningColor,
        warningColorHover,
        errorColor,
        errorColorHover,
        borderRadius,
        lineHeight: lineHeight2,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        clearColor,
        clearColorHover,
        clearColorPressed,
        placeholderColor,
        placeholderColorDisabled,
        iconColor,
        iconColorDisabled,
        iconColorHover,
        iconColorPressed,
        fontWeight
      } = vars;
      return {
        ..._common_default$x,
        fontWeight,
        countTextColorDisabled: textColorDisabled,
        countTextColor: textColor3,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        lineHeight: lineHeight2,
        lineHeightTextarea: lineHeight2,
        borderRadius,
        iconSize: "16px",
        groupLabelColor: inputColor,
        textColor: textColor2,
        textColorDisabled,
        textDecorationColor: textColor2,
        groupLabelTextColor: textColor2,
        caretColor: primaryColor,
        placeholderColor,
        placeholderColorDisabled,
        color: inputColor,
        colorHover: inputColor,
        colorDisabled: inputColorDisabled,
        colorFocus: changeColor(primaryColor, {
          alpha: 0.1
        }),
        groupLabelBorder: "1px solid #0000",
        border: "1px solid #0000",
        borderHover: `1px solid ${primaryColorHover}`,
        borderDisabled: "1px solid #0000",
        borderFocus: `1px solid ${primaryColorHover}`,
        boxShadowFocus: `0 0 8px 0 ${changeColor(primaryColor, {
          alpha: 0.3
        })}`,
        loadingColor: primaryColor,
        loadingColorWarning: warningColor,
        borderWarning: `1px solid ${warningColor}`,
        borderHoverWarning: `1px solid ${warningColorHover}`,
        colorFocusWarning: changeColor(warningColor, {
          alpha: 0.1
        }),
        borderFocusWarning: `1px solid ${warningColorHover}`,
        boxShadowFocusWarning: `0 0 8px 0 ${changeColor(warningColor, {
          alpha: 0.3
        })}`,
        caretColorWarning: warningColor,
        loadingColorError: errorColor,
        borderError: `1px solid ${errorColor}`,
        borderHoverError: `1px solid ${errorColorHover}`,
        colorFocusError: changeColor(errorColor, {
          alpha: 0.1
        }),
        borderFocusError: `1px solid ${errorColorHover}`,
        boxShadowFocusError: `0 0 8px 0 ${changeColor(errorColor, {
          alpha: 0.3
        })}`,
        caretColorError: errorColor,
        clearColor,
        clearColorHover,
        clearColorPressed,
        iconColor,
        iconColorDisabled,
        iconColorHover,
        iconColorPressed,
        suffixTextColor: textColor2
      };
    }
    const inputDark = createTheme({
      name: "Input",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark
      },
      self: self$1g
    });
    const formItemInjectionKey = createInjectionKey("n-form-item");
    function useFormItem(props, {
      defaultSize = "medium",
      mergedSize,
      mergedDisabled
    } = {}) {
      const NFormItem = inject(formItemInjectionKey, null);
      provide(formItemInjectionKey, null);
      const mergedSizeRef = computed(mergedSize ? () => mergedSize(NFormItem) : () => {
        const {
          size
        } = props;
        if (size) return size;
        if (NFormItem) {
          const {
            mergedSize: mergedSize2
          } = NFormItem;
          if (mergedSize2.value !== void 0) return mergedSize2.value;
        }
        return defaultSize;
      });
      const mergedDisabledRef = computed(mergedDisabled ? () => mergedDisabled(NFormItem) : () => {
        const {
          disabled
        } = props;
        if (disabled !== void 0) return disabled;
        if (NFormItem) return NFormItem.disabled.value;
        return false;
      });
      const mergedStatusRef = computed(() => {
        const {
          status
        } = props;
        if (status) return status;
        return NFormItem?.mergedValidationStatus.value;
      });
      onBeforeUnmount(() => {
        if (NFormItem) NFormItem.restoreValidation();
      });
      return {
        mergedSizeRef,
        mergedDisabledRef,
        mergedStatusRef,
        nTriggerFormBlur() {
          if (NFormItem) NFormItem.handleContentBlur();
        },
        nTriggerFormChange() {
          if (NFormItem) NFormItem.handleContentChange();
        },
        nTriggerFormFocus() {
          if (NFormItem) NFormItem.handleContentFocus();
        },
        nTriggerFormInput() {
          if (NFormItem) NFormItem.handleContentInput();
        }
      };
    }
    var IconSwitchTransition_default = /* @__PURE__ */ defineComponent({
      name: "BaseIconSwitchTransition",
      setup(_, {
        slots
      }) {
        const isMountedRef = isMounted();
        return () => (openBlock(), createBlock(Transition, {
          name: "icon-switch-transition",
          appear: isMountedRef.value
        }, normalizeSlots(slots), 1032, ["appear"]));
      }
    });
    const {
      cubicBezierEaseInOut: cubicBezierEaseInOut$1
    } = _common_default$F;
    function iconSwitchTransition({
      originalTransform = "",
      left = 0,
      top = 0,
      transition = `all .3s ${cubicBezierEaseInOut$1} !important`
    } = {}) {
      return [c("&.icon-switch-transition-enter-from, &.icon-switch-transition-leave-to", {
        transform: `${originalTransform} scale(0.75)`,
        left,
        top,
        opacity: 0
      }), c("&.icon-switch-transition-enter-to, &.icon-switch-transition-leave-from", {
        transform: `scale(1) ${originalTransform}`,
        left,
        top,
        opacity: 1
      }), c("&.icon-switch-transition-enter-active, &.icon-switch-transition-leave-active", {
        transformOrigin: "center",
        position: "absolute",
        left,
        top,
        transition
      })];
    }
    var index_cssr_default$4 = c([c("@keyframes rotator", `
 0% {
 -webkit-transform: rotate(0deg);
 transform: rotate(0deg);
 }
 100% {
 -webkit-transform: rotate(360deg);
 transform: rotate(360deg);
 }`), cB("base-loading", `
 position: relative;
 line-height: 0;
 width: 1em;
 height: 1em;
 `, [cE("transition-wrapper", `
 position: absolute;
 width: 100%;
 height: 100%;
 `, [iconSwitchTransition()]), cE("placeholder", `
 position: absolute;
 left: 50%;
 top: 50%;
 transform: translateX(-50%) translateY(-50%);
 `, [iconSwitchTransition({
      left: "50%",
      top: "50%",
      originalTransform: "translateX(-50%) translateY(-50%)"
    })]), cE("container", `
 animation: rotator 3s linear infinite both;
 `, [cE("icon", `
 height: 1em;
 width: 1em;
 `)])])]);
    const _hoisted_1$8 = ["viewBox"];
    const _hoisted_2$8 = ["values", "dur"];
    const _hoisted_3$8 = ["stroke-width", "cx", "cy", "r", "stroke-dasharray", "stroke-dashoffset"];
    const _hoisted_4$6 = ["values", "dur"];
    const _hoisted_5$5 = ["values", "dur"];
    const duration = "1.6s";
    const exposedLoadingProps = {
      strokeWidth: {
        type: Number,
        default: 28
      },
      stroke: {
        type: String,
        default: void 0
      },
      scale: {
        type: Number,
        default: 1
      },
      radius: {
        type: Number,
        default: 100
      }
    };
    var Loading_default = /* @__PURE__ */ defineComponent({
      name: "BaseLoading",
      props: {
        clsPrefix: {
          type: String,
          required: true
        },
        show: {
          type: Boolean,
          default: true
        },
        ...exposedLoadingProps
      },
      setup(props) {
        useStyle("-base-loading", index_cssr_default$4, /* @__PURE__ */ toRef(props, "clsPrefix"));
      },
      render() {
        const {
          clsPrefix,
          radius,
          strokeWidth,
          stroke,
          scale
        } = this;
        const scaledRadius = radius / scale;
        return openBlock(), createElementBlock("div", {
          class: normalizeClass$1(`${clsPrefix}-base-loading`),
          role: "img",
          "aria-label": "loading"
        }, [createVNode(IconSwitchTransition_default, null, {
          default: () => this.show ? (openBlock(), createElementBlock("div", {
            key: "icon",
            class: normalizeClass$1(`${clsPrefix}-base-loading__transition-wrapper`)
          }, [createBaseVNode("div", {
            class: normalizeClass$1(`${clsPrefix}-base-loading__container`)
          }, [(openBlock(), createElementBlock("svg", {
            class: normalizeClass$1(`${clsPrefix}-base-loading__icon`),
            viewBox: `0 0 ${2 * scaledRadius} ${2 * scaledRadius}`,
            xmlns: "http://www.w3.org/2000/svg",
            style: normalizeStyle({
              color: stroke
            })
          }, [createBaseVNode("g", null, [createBaseVNode("animateTransform", {
            attributeName: "transform",
            type: "rotate",
            values: `0 ${scaledRadius} ${scaledRadius};270 ${scaledRadius} ${scaledRadius}`,
            begin: "0s",
            dur: duration,
            fill: "freeze",
            repeatCount: "indefinite"
          }, null, 8, _hoisted_2$8), createBaseVNode("circle", {
            class: normalizeClass$1(`${clsPrefix}-base-loading__icon`),
            fill: "none",
            stroke: "currentColor",
            "stroke-width": strokeWidth,
            "stroke-linecap": "round",
            cx: scaledRadius,
            cy: scaledRadius,
            r: radius - strokeWidth / 2,
            "stroke-dasharray": 5.67 * radius,
            "stroke-dashoffset": 18.48 * radius
          }, [createBaseVNode("animateTransform", {
            attributeName: "transform",
            type: "rotate",
            values: `0 ${scaledRadius} ${scaledRadius};135 ${scaledRadius} ${scaledRadius};450 ${scaledRadius} ${scaledRadius}`,
            begin: "0s",
            dur: duration,
            fill: "freeze",
            repeatCount: "indefinite"
          }, null, 8, _hoisted_4$6), createBaseVNode("animate", {
            attributeName: "stroke-dashoffset",
            values: `${5.67 * radius};${1.42 * radius};${5.67 * radius}`,
            begin: "0s",
            dur: duration,
            fill: "freeze",
            repeatCount: "indefinite"
          }, null, 8, _hoisted_5$5)], 10, _hoisted_3$8)])], 14, _hoisted_1$8))], 2)], 2)) : (openBlock(), createElementBlock("div", {
            key: "placeholder",
            class: normalizeClass$1(`${clsPrefix}-base-loading__placeholder`)
          }, [normalizeVNode(() => this.$slots.default?.())], 2))
        }, 1024)], 2);
      }
    });
    const isBrowser = typeof document !== "undefined" && typeof window !== "undefined";
    const isChrome = isBrowser && "chrome" in window;
    isBrowser && navigator.userAgent.includes("Firefox");
    const isSafari = isBrowser && navigator.userAgent.includes("Safari") && !isChrome;
    function self$1f(vars) {
      const {
        textColor2,
        textColor3,
        textColorDisabled,
        primaryColor,
        primaryColorHover,
        inputColor,
        inputColorDisabled,
        borderColor,
        warningColor,
        warningColorHover,
        errorColor,
        errorColorHover,
        borderRadius,
        lineHeight: lineHeight2,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        actionColor,
        clearColor,
        clearColorHover,
        clearColorPressed,
        placeholderColor,
        placeholderColorDisabled,
        iconColor,
        iconColorDisabled,
        iconColorHover,
        iconColorPressed,
        fontWeight
      } = vars;
      return {
        ..._common_default$x,
        fontWeight,
        countTextColorDisabled: textColorDisabled,
        countTextColor: textColor3,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        lineHeight: lineHeight2,
        lineHeightTextarea: lineHeight2,
        borderRadius,
        iconSize: "16px",
        groupLabelColor: actionColor,
        groupLabelTextColor: textColor2,
        textColor: textColor2,
        textColorDisabled,
        textDecorationColor: textColor2,
        caretColor: primaryColor,
        placeholderColor,
        placeholderColorDisabled,
        color: inputColor,
        colorHover: inputColor,
        colorDisabled: inputColorDisabled,
        colorFocus: inputColor,
        groupLabelBorder: `1px solid ${borderColor}`,
        border: `1px solid ${borderColor}`,
        borderHover: `1px solid ${primaryColorHover}`,
        borderDisabled: `1px solid ${borderColor}`,
        borderFocus: `1px solid ${primaryColorHover}`,
        boxShadowFocus: `0 0 0 2px ${changeColor(primaryColor, {
          alpha: 0.2
        })}`,
        loadingColor: primaryColor,
        loadingColorWarning: warningColor,
        borderWarning: `1px solid ${warningColor}`,
        borderHoverWarning: `1px solid ${warningColorHover}`,
        colorFocusWarning: inputColor,
        borderFocusWarning: `1px solid ${warningColorHover}`,
        boxShadowFocusWarning: `0 0 0 2px ${changeColor(warningColor, {
          alpha: 0.2
        })}`,
        caretColorWarning: warningColor,
        loadingColorError: errorColor,
        borderError: `1px solid ${errorColor}`,
        borderHoverError: `1px solid ${errorColorHover}`,
        colorFocusError: inputColor,
        borderFocusError: `1px solid ${errorColorHover}`,
        boxShadowFocusError: `0 0 0 2px ${changeColor(errorColor, {
          alpha: 0.2
        })}`,
        caretColorError: errorColor,
        clearColor,
        clearColorHover,
        clearColorPressed,
        iconColor,
        iconColorDisabled,
        iconColorHover,
        iconColorPressed,
        suffixTextColor: textColor2
      };
    }
    const inputLight = createTheme({
      name: "Input",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight
      },
      self: self$1f
    });
    function self$1e(vars) {
      const {
        boxShadow2
      } = vars;
      return {
        menuBoxShadow: boxShadow2
      };
    }
    const autoCompleteLight = createTheme({
      name: "AutoComplete",
      common: derived,
      peers: {
        InternalSelectMenu: internalSelectMenuLight,
        Input: inputLight
      },
      self: self$1e
    });
    const autoCompleteDark = {
      name: "AutoComplete",
      common: derived$1,
      peers: {
        InternalSelectMenu: internalSelectMenuDark,
        Input: inputDark
      },
      self: self$1e
    };
    function self$1d(vars) {
      const {
        borderRadius,
        avatarColor,
        cardColor,
        fontSize: fontSize2,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        heightHuge,
        modalColor,
        popoverColor
      } = vars;
      return {
        borderRadius,
        fontSize: fontSize2,
        border: `2px solid ${cardColor}`,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        heightHuge,
        color: composite(cardColor, avatarColor),
        colorModal: composite(modalColor, avatarColor),
        colorPopover: composite(popoverColor, avatarColor)
      };
    }
    const avatarLight = {
      name: "Avatar",
      common: derived,
      self: self$1d
    };
    const avatarDark = {
      name: "Avatar",
      common: derived$1,
      self: self$1d
    };
    function self$1c() {
      return {
        gap: "-12px"
      };
    }
    const avatarGroupLight = createTheme({
      name: "AvatarGroup",
      common: derived,
      peers: {
        Avatar: avatarLight
      },
      self: self$1c
    });
    var _common_default$w = {
      width: "44px",
      height: "44px",
      borderRadius: "22px",
      iconSize: "26px"
    };
    const backTopDark = {
      name: "BackTop",
      common: derived$1,
      self(vars) {
        const {
          popoverColor,
          textColor2,
          primaryColorHover,
          primaryColorPressed
        } = vars;
        return {
          ..._common_default$w,
          color: popoverColor,
          textColor: textColor2,
          iconColor: textColor2,
          iconColorHover: primaryColorHover,
          iconColorPressed: primaryColorPressed,
          boxShadow: "0 2px 8px 0px rgba(0, 0, 0, .12)",
          boxShadowHover: "0 2px 12px 0px rgba(0, 0, 0, .18)",
          boxShadowPressed: "0 2px 12px 0px rgba(0, 0, 0, .18)"
        };
      }
    };
    function self$1b(vars) {
      const {
        popoverColor,
        textColor2,
        primaryColorHover,
        primaryColorPressed
      } = vars;
      return {
        ..._common_default$w,
        color: popoverColor,
        textColor: textColor2,
        iconColor: textColor2,
        iconColorHover: primaryColorHover,
        iconColorPressed: primaryColorPressed,
        boxShadow: "0 2px 8px 0px rgba(0, 0, 0, .12)",
        boxShadowHover: "0 2px 12px 0px rgba(0, 0, 0, .18)",
        boxShadowPressed: "0 2px 12px 0px rgba(0, 0, 0, .18)"
      };
    }
    const backTopLight = {
      name: "BackTop",
      common: derived,
      self: self$1b
    };
    const badgeDark = {
      name: "Badge",
      common: derived$1,
      self(vars) {
        const {
          errorColorSuppl,
          infoColorSuppl,
          successColorSuppl,
          warningColorSuppl,
          fontFamily: fontFamily2
        } = vars;
        return {
          color: errorColorSuppl,
          colorInfo: infoColorSuppl,
          colorSuccess: successColorSuppl,
          colorError: errorColorSuppl,
          colorWarning: warningColorSuppl,
          fontSize: "12px",
          fontFamily: fontFamily2
        };
      }
    };
    const {
      cubicBezierEaseInOut
    } = _common_default$F;
    function fadeInWidthExpandTransition({
      duration: duration2 = ".2s",
      delay = ".1s"
    } = {}) {
      return [c("&.fade-in-width-expand-transition-leave-from, &.fade-in-width-expand-transition-enter-to", {
        opacity: 1
      }), c("&.fade-in-width-expand-transition-leave-to, &.fade-in-width-expand-transition-enter-from", `
 opacity: 0!important;
 margin-left: 0!important;
 margin-right: 0!important;
 `), c("&.fade-in-width-expand-transition-leave-active", `
 overflow: hidden;
 transition:
 opacity ${duration2} ${cubicBezierEaseInOut},
 max-width ${duration2} ${cubicBezierEaseInOut} ${delay},
 margin-left ${duration2} ${cubicBezierEaseInOut} ${delay},
 margin-right ${duration2} ${cubicBezierEaseInOut} ${delay};
 `), c("&.fade-in-width-expand-transition-enter-active", `
 overflow: hidden;
 transition:
 opacity ${duration2} ${cubicBezierEaseInOut} ${delay},
 max-width ${duration2} ${cubicBezierEaseInOut},
 margin-left ${duration2} ${cubicBezierEaseInOut},
 margin-right ${duration2} ${cubicBezierEaseInOut};
 `)];
    }
    var index_cssr_default$3 = cB("base-wave", `
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 border-radius: inherit;
`);
    var Wave_default = /* @__PURE__ */ defineComponent({
      name: "BaseWave",
      props: {
        clsPrefix: {
          type: String,
          required: true
        }
      },
      setup(props) {
        useStyle("-base-wave", index_cssr_default$3, /* @__PURE__ */ toRef(props, "clsPrefix"));
        const selfRef = /* @__PURE__ */ ref(null);
        const activeRef = /* @__PURE__ */ ref(false);
        let animationTimerId = null;
        onBeforeUnmount(() => {
          if (animationTimerId !== null) window.clearTimeout(animationTimerId);
        });
        return {
          active: activeRef,
          selfRef,
          play() {
            if (animationTimerId !== null) {
              window.clearTimeout(animationTimerId);
              activeRef.value = false;
              animationTimerId = null;
            }
            nextTick(() => {
              selfRef.value?.offsetHeight;
              activeRef.value = true;
              animationTimerId = window.setTimeout(() => {
                activeRef.value = false;
                animationTimerId = null;
              }, 1e3);
            });
          }
        };
      },
      render() {
        const {
          clsPrefix
        } = this;
        return openBlock(), createElementBlock("div", {
          ref: "selfRef",
          "aria-hidden": true,
          class: normalizeClass$1([`${clsPrefix}-base-wave`, this.active && `${clsPrefix}-base-wave--active`])
        }, null, 2);
      }
    });
    function self$1a(vars) {
      const {
        errorColor,
        infoColor,
        successColor,
        warningColor,
        fontFamily: fontFamily2
      } = vars;
      return {
        color: errorColor,
        colorInfo: infoColor,
        colorSuccess: successColor,
        colorError: errorColor,
        colorWarning: warningColor,
        fontSize: "12px",
        fontFamily: fontFamily2
      };
    }
    const badgeLight = {
      name: "Badge",
      common: derived,
      self: self$1a
    };
    var _common_default$v = {
      fontWeightActive: "400"
    };
    function self$19(vars) {
      const {
        fontSize: fontSize2,
        textColor3,
        textColor2,
        borderRadius,
        buttonColor2Hover,
        buttonColor2Pressed
      } = vars;
      return {
        ..._common_default$v,
        fontSize: fontSize2,
        itemLineHeight: "1.25",
        itemTextColor: textColor3,
        itemTextColorHover: textColor2,
        itemTextColorPressed: textColor2,
        itemTextColorActive: textColor2,
        itemBorderRadius: borderRadius,
        itemColorHover: buttonColor2Hover,
        itemColorPressed: buttonColor2Pressed,
        separatorColor: textColor3
      };
    }
    const breadcrumbLight = {
      name: "Breadcrumb",
      common: derived,
      self: self$19
    };
    const breadcrumbDark = {
      name: "Breadcrumb",
      common: derived$1,
      self: self$19
    };
    var _common_default$u = {
      paddingTiny: "0 6px",
      paddingSmall: "0 10px",
      paddingMedium: "0 14px",
      paddingLarge: "0 18px",
      paddingRoundTiny: "0 10px",
      paddingRoundSmall: "0 14px",
      paddingRoundMedium: "0 18px",
      paddingRoundLarge: "0 22px",
      iconMarginTiny: "6px",
      iconMarginSmall: "6px",
      iconMarginMedium: "6px",
      iconMarginLarge: "6px",
      iconSizeTiny: "14px",
      iconSizeSmall: "18px",
      iconSizeMedium: "18px",
      iconSizeLarge: "20px",
      rippleDuration: ".6s"
    };
    function self$18(vars) {
      const {
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        borderRadius,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        opacityDisabled,
        textColor2,
        textColor3,
        primaryColorHover,
        primaryColorPressed,
        borderColor,
        primaryColor,
        baseColor,
        infoColor,
        infoColorHover,
        infoColorPressed,
        successColor,
        successColorHover,
        successColorPressed,
        warningColor,
        warningColorHover,
        warningColorPressed,
        errorColor,
        errorColorHover,
        errorColorPressed,
        fontWeight,
        buttonColor2,
        buttonColor2Hover,
        buttonColor2Pressed,
        fontWeightStrong
      } = vars;
      return {
        ..._common_default$u,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        borderRadiusTiny: borderRadius,
        borderRadiusSmall: borderRadius,
        borderRadiusMedium: borderRadius,
        borderRadiusLarge: borderRadius,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        opacityDisabled,
        colorOpacitySecondary: "0.16",
        colorOpacitySecondaryHover: "0.22",
        colorOpacitySecondaryPressed: "0.28",
        colorSecondary: buttonColor2,
        colorSecondaryHover: buttonColor2Hover,
        colorSecondaryPressed: buttonColor2Pressed,
        colorTertiary: buttonColor2,
        colorTertiaryHover: buttonColor2Hover,
        colorTertiaryPressed: buttonColor2Pressed,
        colorQuaternary: "#0000",
        colorQuaternaryHover: buttonColor2Hover,
        colorQuaternaryPressed: buttonColor2Pressed,
        color: "#0000",
        colorHover: "#0000",
        colorPressed: "#0000",
        colorFocus: "#0000",
        colorDisabled: "#0000",
        textColor: textColor2,
        textColorTertiary: textColor3,
        textColorHover: primaryColorHover,
        textColorPressed: primaryColorPressed,
        textColorFocus: primaryColorHover,
        textColorDisabled: textColor2,
        textColorText: textColor2,
        textColorTextHover: primaryColorHover,
        textColorTextPressed: primaryColorPressed,
        textColorTextFocus: primaryColorHover,
        textColorTextDisabled: textColor2,
        textColorGhost: textColor2,
        textColorGhostHover: primaryColorHover,
        textColorGhostPressed: primaryColorPressed,
        textColorGhostFocus: primaryColorHover,
        textColorGhostDisabled: textColor2,
        border: `1px solid ${borderColor}`,
        borderHover: `1px solid ${primaryColorHover}`,
        borderPressed: `1px solid ${primaryColorPressed}`,
        borderFocus: `1px solid ${primaryColorHover}`,
        borderDisabled: `1px solid ${borderColor}`,
        rippleColor: primaryColor,
        colorPrimary: primaryColor,
        colorHoverPrimary: primaryColorHover,
        colorPressedPrimary: primaryColorPressed,
        colorFocusPrimary: primaryColorHover,
        colorDisabledPrimary: primaryColor,
        textColorPrimary: baseColor,
        textColorHoverPrimary: baseColor,
        textColorPressedPrimary: baseColor,
        textColorFocusPrimary: baseColor,
        textColorDisabledPrimary: baseColor,
        textColorTextPrimary: primaryColor,
        textColorTextHoverPrimary: primaryColorHover,
        textColorTextPressedPrimary: primaryColorPressed,
        textColorTextFocusPrimary: primaryColorHover,
        textColorTextDisabledPrimary: textColor2,
        textColorGhostPrimary: primaryColor,
        textColorGhostHoverPrimary: primaryColorHover,
        textColorGhostPressedPrimary: primaryColorPressed,
        textColorGhostFocusPrimary: primaryColorHover,
        textColorGhostDisabledPrimary: primaryColor,
        borderPrimary: `1px solid ${primaryColor}`,
        borderHoverPrimary: `1px solid ${primaryColorHover}`,
        borderPressedPrimary: `1px solid ${primaryColorPressed}`,
        borderFocusPrimary: `1px solid ${primaryColorHover}`,
        borderDisabledPrimary: `1px solid ${primaryColor}`,
        rippleColorPrimary: primaryColor,
        colorInfo: infoColor,
        colorHoverInfo: infoColorHover,
        colorPressedInfo: infoColorPressed,
        colorFocusInfo: infoColorHover,
        colorDisabledInfo: infoColor,
        textColorInfo: baseColor,
        textColorHoverInfo: baseColor,
        textColorPressedInfo: baseColor,
        textColorFocusInfo: baseColor,
        textColorDisabledInfo: baseColor,
        textColorTextInfo: infoColor,
        textColorTextHoverInfo: infoColorHover,
        textColorTextPressedInfo: infoColorPressed,
        textColorTextFocusInfo: infoColorHover,
        textColorTextDisabledInfo: textColor2,
        textColorGhostInfo: infoColor,
        textColorGhostHoverInfo: infoColorHover,
        textColorGhostPressedInfo: infoColorPressed,
        textColorGhostFocusInfo: infoColorHover,
        textColorGhostDisabledInfo: infoColor,
        borderInfo: `1px solid ${infoColor}`,
        borderHoverInfo: `1px solid ${infoColorHover}`,
        borderPressedInfo: `1px solid ${infoColorPressed}`,
        borderFocusInfo: `1px solid ${infoColorHover}`,
        borderDisabledInfo: `1px solid ${infoColor}`,
        rippleColorInfo: infoColor,
        colorSuccess: successColor,
        colorHoverSuccess: successColorHover,
        colorPressedSuccess: successColorPressed,
        colorFocusSuccess: successColorHover,
        colorDisabledSuccess: successColor,
        textColorSuccess: baseColor,
        textColorHoverSuccess: baseColor,
        textColorPressedSuccess: baseColor,
        textColorFocusSuccess: baseColor,
        textColorDisabledSuccess: baseColor,
        textColorTextSuccess: successColor,
        textColorTextHoverSuccess: successColorHover,
        textColorTextPressedSuccess: successColorPressed,
        textColorTextFocusSuccess: successColorHover,
        textColorTextDisabledSuccess: textColor2,
        textColorGhostSuccess: successColor,
        textColorGhostHoverSuccess: successColorHover,
        textColorGhostPressedSuccess: successColorPressed,
        textColorGhostFocusSuccess: successColorHover,
        textColorGhostDisabledSuccess: successColor,
        borderSuccess: `1px solid ${successColor}`,
        borderHoverSuccess: `1px solid ${successColorHover}`,
        borderPressedSuccess: `1px solid ${successColorPressed}`,
        borderFocusSuccess: `1px solid ${successColorHover}`,
        borderDisabledSuccess: `1px solid ${successColor}`,
        rippleColorSuccess: successColor,
        colorWarning: warningColor,
        colorHoverWarning: warningColorHover,
        colorPressedWarning: warningColorPressed,
        colorFocusWarning: warningColorHover,
        colorDisabledWarning: warningColor,
        textColorWarning: baseColor,
        textColorHoverWarning: baseColor,
        textColorPressedWarning: baseColor,
        textColorFocusWarning: baseColor,
        textColorDisabledWarning: baseColor,
        textColorTextWarning: warningColor,
        textColorTextHoverWarning: warningColorHover,
        textColorTextPressedWarning: warningColorPressed,
        textColorTextFocusWarning: warningColorHover,
        textColorTextDisabledWarning: textColor2,
        textColorGhostWarning: warningColor,
        textColorGhostHoverWarning: warningColorHover,
        textColorGhostPressedWarning: warningColorPressed,
        textColorGhostFocusWarning: warningColorHover,
        textColorGhostDisabledWarning: warningColor,
        borderWarning: `1px solid ${warningColor}`,
        borderHoverWarning: `1px solid ${warningColorHover}`,
        borderPressedWarning: `1px solid ${warningColorPressed}`,
        borderFocusWarning: `1px solid ${warningColorHover}`,
        borderDisabledWarning: `1px solid ${warningColor}`,
        rippleColorWarning: warningColor,
        colorError: errorColor,
        colorHoverError: errorColorHover,
        colorPressedError: errorColorPressed,
        colorFocusError: errorColorHover,
        colorDisabledError: errorColor,
        textColorError: baseColor,
        textColorHoverError: baseColor,
        textColorPressedError: baseColor,
        textColorFocusError: baseColor,
        textColorDisabledError: baseColor,
        textColorTextError: errorColor,
        textColorTextHoverError: errorColorHover,
        textColorTextPressedError: errorColorPressed,
        textColorTextFocusError: errorColorHover,
        textColorTextDisabledError: textColor2,
        textColorGhostError: errorColor,
        textColorGhostHoverError: errorColorHover,
        textColorGhostPressedError: errorColorPressed,
        textColorGhostFocusError: errorColorHover,
        textColorGhostDisabledError: errorColor,
        borderError: `1px solid ${errorColor}`,
        borderHoverError: `1px solid ${errorColorHover}`,
        borderPressedError: `1px solid ${errorColorPressed}`,
        borderFocusError: `1px solid ${errorColorHover}`,
        borderDisabledError: `1px solid ${errorColor}`,
        rippleColorError: errorColor,
        waveOpacity: "0.6",
        fontWeight,
        fontWeightStrong
      };
    }
    const buttonLight = {
      name: "Button",
      common: derived,
      self: self$18
    };
    const buttonDark = {
      name: "Button",
      common: derived$1,
      self(vars) {
        const commonSelf = self$18(vars);
        commonSelf.waveOpacity = "0.8";
        commonSelf.colorOpacitySecondary = "0.16";
        commonSelf.colorOpacitySecondaryHover = "0.2";
        commonSelf.colorOpacitySecondaryPressed = "0.12";
        return commonSelf;
      }
    };
    function createHoverColor(rgb) {
      return composite(rgb, [255, 255, 255, 0.16]);
    }
    function createPressedColor(rgb) {
      return composite(rgb, [0, 0, 0, 0.12]);
    }
    const buttonGroupInjectionKey = createInjectionKey("n-button-group");
    var index_cssr_default$2 = c([cB("button", `
 margin: 0;
 font-weight: var(--n-font-weight);
 line-height: 1;
 font-family: inherit;
 padding: var(--n-padding);
 height: var(--n-height);
 font-size: var(--n-font-size);
 border-radius: var(--n-border-radius);
 color: var(--n-text-color);
 background-color: var(--n-color);
 width: var(--n-width);
 white-space: nowrap;
 outline: none;
 position: relative;
 z-index: auto;
 border: none;
 display: inline-flex;
 flex-wrap: nowrap;
 flex-shrink: 0;
 align-items: center;
 justify-content: center;
 user-select: none;
 -webkit-user-select: none;
 text-align: center;
 cursor: pointer;
 text-decoration: none;
 transition:
 color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 opacity .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `, [cM("color", [cE("border", {
      borderColor: "var(--n-border-color)"
    }), cM("disabled", [cE("border", {
      borderColor: "var(--n-border-color-disabled)"
    })]), cNotM("disabled", [c("&:focus", [cE("state-border", {
      borderColor: "var(--n-border-color-focus)"
    })]), c("&:hover", [cE("state-border", {
      borderColor: "var(--n-border-color-hover)"
    })]), c("&:active", [cE("state-border", {
      borderColor: "var(--n-border-color-pressed)"
    })]), cM("pressed", [cE("state-border", {
      borderColor: "var(--n-border-color-pressed)"
    })])])]), cM("disabled", {
      backgroundColor: "var(--n-color-disabled)",
      color: "var(--n-text-color-disabled)"
    }, [cE("border", {
      border: "var(--n-border-disabled)"
    })]), cNotM("disabled", [c("&:focus", {
      backgroundColor: "var(--n-color-focus)",
      color: "var(--n-text-color-focus)"
    }, [cE("state-border", {
      border: "var(--n-border-focus)"
    })]), c("&:hover", {
      backgroundColor: "var(--n-color-hover)",
      color: "var(--n-text-color-hover)"
    }, [cE("state-border", {
      border: "var(--n-border-hover)"
    })]), c("&:active", {
      backgroundColor: "var(--n-color-pressed)",
      color: "var(--n-text-color-pressed)"
    }, [cE("state-border", {
      border: "var(--n-border-pressed)"
    })]), cM("pressed", {
      backgroundColor: "var(--n-color-pressed)",
      color: "var(--n-text-color-pressed)"
    }, [cE("state-border", {
      border: "var(--n-border-pressed)"
    })])]), cM("loading", "cursor: wait;"), cB("base-wave", `
 pointer-events: none;
 top: 0;
 right: 0;
 bottom: 0;
 left: 0;
 animation-iteration-count: 1;
 animation-duration: var(--n-ripple-duration);
 animation-timing-function: var(--n-bezier-ease-out), var(--n-bezier-ease-out);
 `, [cM("active", {
      zIndex: 1,
      animationName: "button-wave-spread, button-wave-opacity"
    })]), isBrowser && "MozBoxSizing" in document.createElement("div").style ? c("&::moz-focus-inner", {
      border: 0
    }) : null, cE("border, state-border", `
 position: absolute;
 left: 0;
 top: 0;
 right: 0;
 bottom: 0;
 border-radius: inherit;
 transition: border-color .3s var(--n-bezier);
 pointer-events: none;
 `), cE("border", `
 border: var(--n-border);
 `), cE("state-border", `
 border: var(--n-border);
 border-color: #0000;
 z-index: 1;
 `), cE("icon", `
 margin: var(--n-icon-margin);
 margin-left: 0;
 height: var(--n-icon-size);
 width: var(--n-icon-size);
 max-width: var(--n-icon-size);
 font-size: var(--n-icon-size);
 position: relative;
 flex-shrink: 0;
 `, [cB("icon-slot", `
 height: var(--n-icon-size);
 width: var(--n-icon-size);
 position: absolute;
 left: 0;
 top: 50%;
 transform: translateY(-50%);
 display: flex;
 align-items: center;
 justify-content: center;
 `, [iconSwitchTransition({
      top: "50%",
      originalTransform: "translateY(-50%)"
    })]), fadeInWidthExpandTransition()]), cE("content", `
 display: flex;
 align-items: center;
 flex-wrap: nowrap;
 min-width: 0;
 `, [c("~", [cE("icon", {
      margin: "var(--n-icon-margin)",
      marginRight: 0
    })])]), cM("block", `
 display: flex;
 width: 100%;
 `), cM("dashed", [cE("border, state-border", {
      borderStyle: "dashed !important"
    })]), cM("disabled", {
      cursor: "not-allowed",
      opacity: "var(--n-opacity-disabled)"
    })]), c("@keyframes button-wave-spread", {
      from: {
        boxShadow: "0 0 0.5px 0 var(--n-ripple-color)"
      },
      to: {
        boxShadow: "0 0 0.5px 4.5px var(--n-ripple-color)"
      }
    }), c("@keyframes button-wave-opacity", {
      from: {
        opacity: "var(--n-wave-opacity)"
      },
      to: {
        opacity: 0
      }
    })]);
    const buttonProps = {
      ...useTheme.props,
      color: String,
      textColor: String,
      text: Boolean,
      block: Boolean,
      loading: Boolean,
      disabled: Boolean,
      circle: Boolean,
      size: String,
      ghost: Boolean,
      round: Boolean,
      secondary: Boolean,
      tertiary: Boolean,
      quaternary: Boolean,
      strong: Boolean,
      focusable: {
        type: Boolean,
        default: true
      },
      keyboard: {
        type: Boolean,
        default: true
      },
      tag: {
        type: String,
        default: "button"
      },
      type: {
        type: String,
        default: "default"
      },
      dashed: Boolean,
      renderIcon: Function,
      iconPlacement: {
        type: String,
        default: "left"
      },
      attrType: {
        type: String,
        default: "button"
      },
      bordered: {
        type: Boolean,
        default: true
      },
      onClick: [Function, Array],
      nativeFocusBehavior: {
        type: Boolean,
        default: !isSafari
      },
      spinProps: Object
    };
    const Button = /* @__PURE__ */ defineComponent({
      name: "Button",
      props: buttonProps,
      slots: Object,
      setup(props) {
        const selfElRef = /* @__PURE__ */ ref(null);
        const waveElRef = /* @__PURE__ */ ref(null);
        const enterPressedRef = /* @__PURE__ */ ref(false);
        const showBorderRef = useMemo(() => {
          return !props.quaternary && !props.tertiary && !props.secondary && !props.text && (!props.color || props.ghost || props.dashed) && props.bordered;
        });
        const NButtonGroup = inject(buttonGroupInjectionKey, {});
        const {
          inlineThemeDisabled,
          mergedClsPrefixRef,
          mergedRtlRef,
          mergedComponentPropsRef
        } = useConfig(props);
        const {
          mergedSizeRef
        } = useFormItem({}, {
          defaultSize: "medium",
          mergedSize: (NFormItem) => {
            const {
              size
            } = props;
            if (size) return size;
            const {
              size: buttonGroupSize
            } = NButtonGroup;
            if (buttonGroupSize) return buttonGroupSize;
            const {
              mergedSize: formItemSize
            } = NFormItem || {};
            if (formItemSize) return formItemSize.value;
            const configSize = mergedComponentPropsRef?.value?.Button?.size;
            if (configSize) return configSize;
            return "medium";
          }
        });
        const mergedFocusableRef = computed(() => {
          return props.focusable && !props.disabled;
        });
        const handleMousedown = (e) => {
          if (!mergedFocusableRef.value) e.preventDefault();
          if (props.nativeFocusBehavior) return;
          e.preventDefault();
          if (props.disabled) return;
          if (mergedFocusableRef.value) selfElRef.value?.focus({
            preventScroll: true
          });
        };
        const handleClick = (e) => {
          if (!props.disabled && !props.loading) {
            const {
              onClick
            } = props;
            if (onClick) call(onClick, e);
            if (!props.text) waveElRef.value?.play();
          }
        };
        const handleKeyup = (e) => {
          switch (e.key) {
            case "Enter":
              if (!props.keyboard) return;
              enterPressedRef.value = false;
          }
        };
        const handleKeydown = (e) => {
          switch (e.key) {
            case "Enter":
              if (!props.keyboard || props.loading) {
                e.preventDefault();
                return;
              }
              enterPressedRef.value = true;
          }
        };
        const handleBlur = () => {
          enterPressedRef.value = false;
        };
        const themeRef = useTheme("Button", "-button", index_cssr_default$2, buttonLight, props, mergedClsPrefixRef);
        const rtlEnabledRef = useRtl("Button", mergedRtlRef, mergedClsPrefixRef);
        const cssVarsRef = computed(() => {
          const {
            common: {
              cubicBezierEaseInOut: cubicBezierEaseInOut2,
              cubicBezierEaseOut
            },
            self: self2
          } = themeRef.value;
          const {
            rippleDuration,
            opacityDisabled,
            fontWeight,
            fontWeightStrong
          } = self2;
          const size = mergedSizeRef.value;
          const {
            dashed,
            type,
            ghost,
            text,
            color,
            round,
            circle,
            textColor,
            secondary,
            tertiary,
            quaternary,
            strong
          } = props;
          const fontProps = {
            "--n-font-weight": strong ? fontWeightStrong : fontWeight
          };
          let colorProps = {
            "--n-color": "initial",
            "--n-color-hover": "initial",
            "--n-color-pressed": "initial",
            "--n-color-focus": "initial",
            "--n-color-disabled": "initial",
            "--n-ripple-color": "initial",
            "--n-text-color": "initial",
            "--n-text-color-hover": "initial",
            "--n-text-color-pressed": "initial",
            "--n-text-color-focus": "initial",
            "--n-text-color-disabled": "initial"
          };
          const typeIsTertiary = type === "tertiary";
          const typeIsDefault = type === "default";
          const mergedType = typeIsTertiary ? "default" : type;
          if (text) {
            const propTextColor = textColor || color;
            colorProps = {
              "--n-color": "#0000",
              "--n-color-hover": "#0000",
              "--n-color-pressed": "#0000",
              "--n-color-focus": "#0000",
              "--n-color-disabled": "#0000",
              "--n-ripple-color": "#0000",
              "--n-text-color": propTextColor || self2[createKey("textColorText", mergedType)],
              "--n-text-color-hover": propTextColor ? createHoverColor(propTextColor) : self2[createKey("textColorTextHover", mergedType)],
              "--n-text-color-pressed": propTextColor ? createPressedColor(propTextColor) : self2[createKey("textColorTextPressed", mergedType)],
              "--n-text-color-focus": propTextColor ? createHoverColor(propTextColor) : self2[createKey("textColorTextHover", mergedType)],
              "--n-text-color-disabled": propTextColor || self2[createKey("textColorTextDisabled", mergedType)]
            };
          } else if (ghost || dashed) {
            const mergedTextColor = textColor || color;
            colorProps = {
              "--n-color": "#0000",
              "--n-color-hover": "#0000",
              "--n-color-pressed": "#0000",
              "--n-color-focus": "#0000",
              "--n-color-disabled": "#0000",
              "--n-ripple-color": color || self2[createKey("rippleColor", mergedType)],
              "--n-text-color": mergedTextColor || self2[createKey("textColorGhost", mergedType)],
              "--n-text-color-hover": mergedTextColor ? createHoverColor(mergedTextColor) : self2[createKey("textColorGhostHover", mergedType)],
              "--n-text-color-pressed": mergedTextColor ? createPressedColor(mergedTextColor) : self2[createKey("textColorGhostPressed", mergedType)],
              "--n-text-color-focus": mergedTextColor ? createHoverColor(mergedTextColor) : self2[createKey("textColorGhostHover", mergedType)],
              "--n-text-color-disabled": mergedTextColor || self2[createKey("textColorGhostDisabled", mergedType)]
            };
          } else if (secondary) {
            const typeTextColor = typeIsDefault ? self2.textColor : typeIsTertiary ? self2.textColorTertiary : self2[createKey("color", mergedType)];
            const mergedTextColor = color || typeTextColor;
            const isColoredType = type !== "default" && type !== "tertiary";
            colorProps = {
              "--n-color": isColoredType ? changeColor(mergedTextColor, {
                alpha: Number(self2.colorOpacitySecondary)
              }) : self2.colorSecondary,
              "--n-color-hover": isColoredType ? changeColor(mergedTextColor, {
                alpha: Number(self2.colorOpacitySecondaryHover)
              }) : self2.colorSecondaryHover,
              "--n-color-pressed": isColoredType ? changeColor(mergedTextColor, {
                alpha: Number(self2.colorOpacitySecondaryPressed)
              }) : self2.colorSecondaryPressed,
              "--n-color-focus": isColoredType ? changeColor(mergedTextColor, {
                alpha: Number(self2.colorOpacitySecondaryHover)
              }) : self2.colorSecondaryHover,
              "--n-color-disabled": self2.colorSecondary,
              "--n-ripple-color": "#0000",
              "--n-text-color": mergedTextColor,
              "--n-text-color-hover": mergedTextColor,
              "--n-text-color-pressed": mergedTextColor,
              "--n-text-color-focus": mergedTextColor,
              "--n-text-color-disabled": mergedTextColor
            };
          } else if (tertiary || quaternary) {
            const typeColor = typeIsDefault ? self2.textColor : typeIsTertiary ? self2.textColorTertiary : self2[createKey("color", mergedType)];
            const mergedColor = color || typeColor;
            if (tertiary) {
              colorProps["--n-color"] = self2.colorTertiary;
              colorProps["--n-color-hover"] = self2.colorTertiaryHover;
              colorProps["--n-color-pressed"] = self2.colorTertiaryPressed;
              colorProps["--n-color-focus"] = self2.colorSecondaryHover;
              colorProps["--n-color-disabled"] = self2.colorTertiary;
            } else {
              colorProps["--n-color"] = self2.colorQuaternary;
              colorProps["--n-color-hover"] = self2.colorQuaternaryHover;
              colorProps["--n-color-pressed"] = self2.colorQuaternaryPressed;
              colorProps["--n-color-focus"] = self2.colorQuaternaryHover;
              colorProps["--n-color-disabled"] = self2.colorQuaternary;
            }
            colorProps["--n-ripple-color"] = "#0000";
            colorProps["--n-text-color"] = mergedColor;
            colorProps["--n-text-color-hover"] = mergedColor;
            colorProps["--n-text-color-pressed"] = mergedColor;
            colorProps["--n-text-color-focus"] = mergedColor;
            colorProps["--n-text-color-disabled"] = mergedColor;
          } else colorProps = {
            "--n-color": color || self2[createKey("color", mergedType)],
            "--n-color-hover": color ? createHoverColor(color) : self2[createKey("colorHover", mergedType)],
            "--n-color-pressed": color ? createPressedColor(color) : self2[createKey("colorPressed", mergedType)],
            "--n-color-focus": color ? createHoverColor(color) : self2[createKey("colorFocus", mergedType)],
            "--n-color-disabled": color || self2[createKey("colorDisabled", mergedType)],
            "--n-ripple-color": color || self2[createKey("rippleColor", mergedType)],
            "--n-text-color": textColor || (color ? self2.textColorPrimary : typeIsTertiary ? self2.textColorTertiary : self2[createKey("textColor", mergedType)]),
            "--n-text-color-hover": textColor || (color ? self2.textColorHoverPrimary : self2[createKey("textColorHover", mergedType)]),
            "--n-text-color-pressed": textColor || (color ? self2.textColorPressedPrimary : self2[createKey("textColorPressed", mergedType)]),
            "--n-text-color-focus": textColor || (color ? self2.textColorFocusPrimary : self2[createKey("textColorFocus", mergedType)]),
            "--n-text-color-disabled": textColor || (color ? self2.textColorDisabledPrimary : self2[createKey("textColorDisabled", mergedType)])
          };
          let borderProps = {
            "--n-border": "initial",
            "--n-border-hover": "initial",
            "--n-border-pressed": "initial",
            "--n-border-focus": "initial",
            "--n-border-disabled": "initial"
          };
          if (text) borderProps = {
            "--n-border": "none",
            "--n-border-hover": "none",
            "--n-border-pressed": "none",
            "--n-border-focus": "none",
            "--n-border-disabled": "none"
          };
          else borderProps = {
            "--n-border": self2[createKey("border", mergedType)],
            "--n-border-hover": self2[createKey("borderHover", mergedType)],
            "--n-border-pressed": self2[createKey("borderPressed", mergedType)],
            "--n-border-focus": self2[createKey("borderFocus", mergedType)],
            "--n-border-disabled": self2[createKey("borderDisabled", mergedType)]
          };
          const {
            [createKey("height", size)]: height,
            [createKey("fontSize", size)]: fontSize2,
            [createKey("padding", size)]: padding,
            [createKey("paddingRound", size)]: paddingRound,
            [createKey("iconSize", size)]: iconSize,
            [createKey("borderRadius", size)]: borderRadius,
            [createKey("iconMargin", size)]: iconMargin,
            waveOpacity
          } = self2;
          const sizeProps = {
            "--n-width": circle && !text ? height : "initial",
            "--n-height": text ? "initial" : height,
            "--n-font-size": fontSize2,
            "--n-padding": circle ? "initial" : text ? "initial" : round ? paddingRound : padding,
            "--n-icon-size": iconSize,
            "--n-icon-margin": iconMargin,
            "--n-border-radius": text ? "initial" : circle || round ? height : borderRadius
          };
          return {
            "--n-bezier": cubicBezierEaseInOut2,
            "--n-bezier-ease-out": cubicBezierEaseOut,
            "--n-ripple-duration": rippleDuration,
            "--n-opacity-disabled": opacityDisabled,
            "--n-wave-opacity": waveOpacity,
            ...fontProps,
            ...colorProps,
            ...borderProps,
            ...sizeProps
          };
        });
        const themeClassHandle = inlineThemeDisabled ? useThemeClass("button", computed(() => {
          let hash = "";
          const {
            dashed,
            type,
            ghost,
            text,
            color,
            round,
            circle,
            textColor,
            secondary,
            tertiary,
            quaternary,
            strong
          } = props;
          if (dashed) hash += "a";
          if (ghost) hash += "b";
          if (text) hash += "c";
          if (round) hash += "d";
          if (circle) hash += "e";
          if (secondary) hash += "f";
          if (tertiary) hash += "g";
          if (quaternary) hash += "h";
          if (strong) hash += "i";
          if (color) hash += `j${color2Class(color)}`;
          if (textColor) hash += `k${color2Class(textColor)}`;
          const {
            value: size
          } = mergedSizeRef;
          hash += `l${size[0]}`;
          hash += `m${type[0]}`;
          return hash;
        }), cssVarsRef, props) : void 0;
        return {
          selfElRef,
          waveElRef,
          mergedClsPrefix: mergedClsPrefixRef,
          mergedFocusable: mergedFocusableRef,
          mergedSize: mergedSizeRef,
          showBorder: showBorderRef,
          enterPressed: enterPressedRef,
          rtlEnabled: rtlEnabledRef,
          handleMousedown,
          handleKeydown,
          handleBlur,
          handleKeyup,
          handleClick,
          customColorCssVars: computed(() => {
            const {
              color
            } = props;
            if (!color) return null;
            const hoverColor = createHoverColor(color);
            return {
              "--n-border-color": color,
              "--n-border-color-hover": hoverColor,
              "--n-border-color-pressed": createPressedColor(color),
              "--n-border-color-focus": hoverColor,
              "--n-border-color-disabled": color
            };
          }),
          cssVars: inlineThemeDisabled ? void 0 : cssVarsRef,
          themeClass: themeClassHandle?.themeClass,
          onRender: themeClassHandle?.onRender
        };
      },
      render() {
        const {
          mergedClsPrefix,
          tag: Component,
          onRender
        } = this;
        onRender?.();
        const children = resolveWrappedSlot(this.$slots.default, (children2) => children2 && (openBlock(), createElementBlock("span", {
          class: normalizeClass$1(`${mergedClsPrefix}-button__content`)
        }, [normalizeVNode(() => children2)], 2)));
        return openBlock(), createBlock(Component, {
          ref: "selfElRef",
          class: normalizeClass$1([this.themeClass, `${mergedClsPrefix}-button`, `${mergedClsPrefix}-button--${this.type}-type`, `${mergedClsPrefix}-button--${this.mergedSize}-type`, this.rtlEnabled && `${mergedClsPrefix}-button--rtl`, this.disabled && `${mergedClsPrefix}-button--disabled`, this.block && `${mergedClsPrefix}-button--block`, this.enterPressed && `${mergedClsPrefix}-button--pressed`, !this.text && this.dashed && `${mergedClsPrefix}-button--dashed`, this.color && `${mergedClsPrefix}-button--color`, this.secondary && `${mergedClsPrefix}-button--secondary`, this.loading && `${mergedClsPrefix}-button--loading`, this.ghost && `${mergedClsPrefix}-button--ghost`]),
          tabindex: this.mergedFocusable ? 0 : -1,
          type: this.attrType,
          style: normalizeStyle(this.cssVars),
          disabled: this.disabled,
          onClick: this.handleClick,
          onBlur: this.handleBlur,
          onMousedown: this.handleMousedown,
          onKeyup: this.handleKeyup,
          onKeydown: this.handleKeydown
        }, {
          default: withCtx(() => [normalizeVNode(() => this.iconPlacement === "right" && children), createVNode(FadeInExpandTransition_default, {
            width: true
          }, {
            default: () => resolveWrappedSlot(this.$slots.icon, (children2) => (this.loading || this.renderIcon || children2) && (openBlock(), createElementBlock("span", {
              class: normalizeClass$1(`${mergedClsPrefix}-button__icon`),
              style: normalizeStyle({
                margin: isSlotEmpty(this.$slots.default) ? "0" : ""
              })
            }, [createVNode(IconSwitchTransition_default, null, {
              default: () => this.loading ? (openBlock(), createBlock(Loading_default, mergeProps({
                clsPrefix: mergedClsPrefix,
                key: "loading",
                class: `${mergedClsPrefix}-icon-slot`,
                strokeWidth: 20
              }, this.spinProps), null, 16, ["clsPrefix", "class"])) : (openBlock(), createElementBlock("div", {
                key: "icon",
                class: normalizeClass$1(`${mergedClsPrefix}-icon-slot`),
                role: "none"
              }, [this.renderIcon ? (openBlock(), createElementBlock(Fragment, {
                key: 0
              }, [normalizeVNode(() => this.renderIcon())], 64)) : (openBlock(), createElementBlock(Fragment, {
                key: 1
              }, [normalizeVNode(() => children2)], 64))], 2))
            }, 1024)], 6)))
          }, 1024), normalizeVNode(() => this.iconPlacement === "left" && children), !this.text ? (openBlock(), createBlock(Wave_default, {
            key: 0,
            ref: "waveElRef",
            clsPrefix: mergedClsPrefix
          }, null, 8, ["clsPrefix"])) : normalizeVNode(() => null), this.showBorder ? (openBlock(), createElementBlock("div", {
            key: 2,
            "aria-hidden": true,
            class: normalizeClass$1(`${mergedClsPrefix}-button__border`),
            style: normalizeStyle(this.customColorCssVars)
          }, null, 6)) : normalizeVNode(() => null), this.showBorder ? (openBlock(), createElementBlock("div", {
            key: 4,
            "aria-hidden": true,
            class: normalizeClass$1(`${mergedClsPrefix}-button__state-border`),
            style: normalizeStyle(this.customColorCssVars)
          }, null, 6)) : normalizeVNode(() => null)]),
          _: 2
        }, 1032, ["class", "tabindex", "type", "style", "disabled", "onClick", "onBlur", "onMousedown", "onKeyup", "onKeydown"]);
      }
    });
    var _common_default$t = {
      titleFontSize: "22px"
    };
    function self$17(vars) {
      const {
        borderRadius,
        fontSize: fontSize2,
        lineHeight: lineHeight2,
        textColor2,
        textColor1,
        textColorDisabled,
        dividerColor,
        fontWeightStrong,
        primaryColor,
        baseColor,
        hoverColor,
        cardColor,
        modalColor,
        popoverColor
      } = vars;
      return {
        ..._common_default$t,
        borderRadius,
        borderColor: composite(cardColor, dividerColor),
        borderColorModal: composite(modalColor, dividerColor),
        borderColorPopover: composite(popoverColor, dividerColor),
        textColor: textColor2,
        titleFontWeight: fontWeightStrong,
        titleTextColor: textColor1,
        dayTextColor: textColorDisabled,
        fontSize: fontSize2,
        lineHeight: lineHeight2,
        dateColorCurrent: primaryColor,
        dateTextColorCurrent: baseColor,
        cellColorHover: composite(cardColor, hoverColor),
        cellColorHoverModal: composite(modalColor, hoverColor),
        cellColorHoverPopover: composite(popoverColor, hoverColor),
        cellColor: cardColor,
        cellColorModal: modalColor,
        cellColorPopover: popoverColor,
        barColor: primaryColor
      };
    }
    const calendarLight = createTheme({
      name: "Calendar",
      common: derived,
      peers: {
        Button: buttonLight
      },
      self: self$17
    });
    var _common_default$s = {
      paddingSmall: "12px 16px 12px",
      paddingMedium: "19px 24px 20px",
      paddingLarge: "23px 32px 24px",
      paddingHuge: "27px 40px 28px",
      titleFontSizeSmall: "16px",
      titleFontSizeMedium: "18px",
      titleFontSizeLarge: "18px",
      titleFontSizeHuge: "18px",
      closeIconSize: "18px",
      closeSize: "22px"
    };
    function self$16(vars) {
      const {
        primaryColor,
        borderRadius,
        lineHeight: lineHeight2,
        fontSize: fontSize2,
        cardColor,
        textColor2,
        textColor1,
        dividerColor,
        fontWeightStrong,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeColorHover,
        closeColorPressed,
        modalColor,
        boxShadow1,
        popoverColor,
        actionColor
      } = vars;
      return {
        ..._common_default$s,
        lineHeight: lineHeight2,
        color: cardColor,
        colorModal: modalColor,
        colorPopover: popoverColor,
        colorTarget: primaryColor,
        colorEmbedded: actionColor,
        colorEmbeddedModal: actionColor,
        colorEmbeddedPopover: actionColor,
        textColor: textColor2,
        titleTextColor: textColor1,
        borderColor: dividerColor,
        actionColor,
        titleFontWeight: fontWeightStrong,
        closeColorHover,
        closeColorPressed,
        closeBorderRadius: borderRadius,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        fontSizeSmall: fontSize2,
        fontSizeMedium: fontSize2,
        fontSizeLarge: fontSize2,
        fontSizeHuge: fontSize2,
        boxShadow: boxShadow1,
        borderRadius
      };
    }
    const cardLight = {
      name: "Card",
      common: derived,
      self: self$16
    };
    const cardDark = {
      name: "Card",
      common: derived$1,
      self(vars) {
        const commonSelf = self$16(vars);
        const {
          cardColor,
          modalColor,
          popoverColor
        } = vars;
        commonSelf.colorEmbedded = cardColor;
        commonSelf.colorEmbeddedModal = modalColor;
        commonSelf.colorEmbeddedPopover = popoverColor;
        return commonSelf;
      }
    };
    function self$15() {
      return {
        dotSize: "8px",
        dotColor: "rgba(255, 255, 255, .3)",
        dotColorActive: "rgba(255, 255, 255, 1)",
        dotColorFocus: "rgba(255, 255, 255, .5)",
        dotLineWidth: "16px",
        dotLineWidthActive: "24px",
        arrowColor: "#eee"
      };
    }
    const carouselLight = {
      name: "Carousel",
      common: derived,
      self: self$15
    };
    var _common_default$r = {
      sizeSmall: "14px",
      sizeMedium: "16px",
      sizeLarge: "18px",
      labelPadding: "0 8px",
      labelFontWeight: "400"
    };
    function self$14(vars) {
      const {
        baseColor,
        inputColorDisabled,
        cardColor,
        modalColor,
        popoverColor,
        textColorDisabled,
        borderColor,
        primaryColor,
        textColor2,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        borderRadiusSmall,
        lineHeight: lineHeight2
      } = vars;
      return {
        ..._common_default$r,
        labelLineHeight: lineHeight2,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        borderRadius: borderRadiusSmall,
        color: baseColor,
        colorChecked: primaryColor,
        colorDisabled: inputColorDisabled,
        colorDisabledChecked: inputColorDisabled,
        colorTableHeader: cardColor,
        colorTableHeaderModal: modalColor,
        colorTableHeaderPopover: popoverColor,
        checkMarkColor: baseColor,
        checkMarkColorDisabled: textColorDisabled,
        checkMarkColorDisabledChecked: textColorDisabled,
        border: `1px solid ${borderColor}`,
        borderDisabled: `1px solid ${borderColor}`,
        borderDisabledChecked: `1px solid ${borderColor}`,
        borderChecked: `1px solid ${primaryColor}`,
        borderFocus: `1px solid ${primaryColor}`,
        boxShadowFocus: `0 0 0 2px ${changeColor(primaryColor, {
          alpha: 0.3
        })}`,
        textColor: textColor2,
        textColorDisabled
      };
    }
    const checkboxLight = {
      name: "Checkbox",
      common: derived,
      self: self$14
    };
    const checkboxDark = {
      name: "Checkbox",
      common: derived$1,
      self(vars) {
        const {
          cardColor
        } = vars;
        const commonSelf = self$14(vars);
        commonSelf.color = "#0000";
        commonSelf.checkMarkColor = cardColor;
        return commonSelf;
      }
    };
    function self$13(vars) {
      const {
        borderRadius,
        textColor2,
        textColorDisabled,
        inputColor,
        inputColorDisabled,
        primaryColor,
        primaryColorHover,
        warningColor,
        warningColorHover,
        errorColor,
        errorColorHover,
        borderColor,
        iconColor,
        iconColorDisabled,
        clearColor,
        clearColorHover,
        clearColorPressed,
        placeholderColor,
        placeholderColorDisabled,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        fontWeight
      } = vars;
      return {
        ..._common_default$A,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        borderRadius,
        fontWeight,
        textColor: textColor2,
        textColorDisabled,
        placeholderColor,
        placeholderColorDisabled,
        color: inputColor,
        colorDisabled: inputColorDisabled,
        colorActive: inputColor,
        border: `1px solid ${borderColor}`,
        borderHover: `1px solid ${primaryColorHover}`,
        borderActive: `1px solid ${primaryColor}`,
        borderFocus: `1px solid ${primaryColorHover}`,
        boxShadowHover: "none",
        boxShadowActive: `0 0 0 2px ${changeColor(primaryColor, {
          alpha: 0.2
        })}`,
        boxShadowFocus: `0 0 0 2px ${changeColor(primaryColor, {
          alpha: 0.2
        })}`,
        caretColor: primaryColor,
        arrowColor: iconColor,
        arrowColorDisabled: iconColorDisabled,
        loadingColor: primaryColor,
        borderWarning: `1px solid ${warningColor}`,
        borderHoverWarning: `1px solid ${warningColorHover}`,
        borderActiveWarning: `1px solid ${warningColor}`,
        borderFocusWarning: `1px solid ${warningColorHover}`,
        boxShadowHoverWarning: "none",
        boxShadowActiveWarning: `0 0 0 2px ${changeColor(warningColor, {
          alpha: 0.2
        })}`,
        boxShadowFocusWarning: `0 0 0 2px ${changeColor(warningColor, {
          alpha: 0.2
        })}`,
        colorActiveWarning: inputColor,
        caretColorWarning: warningColor,
        borderError: `1px solid ${errorColor}`,
        borderHoverError: `1px solid ${errorColorHover}`,
        borderActiveError: `1px solid ${errorColor}`,
        borderFocusError: `1px solid ${errorColorHover}`,
        boxShadowHoverError: "none",
        boxShadowActiveError: `0 0 0 2px ${changeColor(errorColor, {
          alpha: 0.2
        })}`,
        boxShadowFocusError: `0 0 0 2px ${changeColor(errorColor, {
          alpha: 0.2
        })}`,
        colorActiveError: inputColor,
        caretColorError: errorColor,
        clearColor,
        clearColorHover,
        clearColorPressed
      };
    }
    const internalSelectionLight = createTheme({
      name: "InternalSelection",
      common: derived,
      peers: {
        Popover: popoverLight
      },
      self: self$13
    });
    function self$12(vars) {
      const {
        borderRadius,
        boxShadow2,
        popoverColor,
        textColor2,
        textColor3,
        primaryColor,
        textColorDisabled,
        dividerColor,
        hoverColor,
        fontSizeMedium,
        heightMedium
      } = vars;
      return {
        menuBorderRadius: borderRadius,
        menuColor: popoverColor,
        menuBoxShadow: boxShadow2,
        menuDividerColor: dividerColor,
        menuHeight: "calc(var(--n-option-height) * 6.6)",
        optionArrowColor: textColor3,
        optionHeight: heightMedium,
        optionFontSize: fontSizeMedium,
        optionColorHover: hoverColor,
        optionTextColor: textColor2,
        optionTextColorActive: primaryColor,
        optionTextColorDisabled: textColorDisabled,
        optionCheckMarkColor: primaryColor,
        loadingColor: primaryColor,
        columnWidth: "180px"
      };
    }
    const cascaderLight = createTheme({
      name: "Cascader",
      common: derived,
      peers: {
        InternalSelectMenu: internalSelectMenuLight,
        InternalSelection: internalSelectionLight,
        Scrollbar: scrollbarLight,
        Checkbox: checkboxLight,
        Empty: emptyLight
      },
      self: self$12
    });
    const cascaderDark = {
      name: "Cascader",
      common: derived$1,
      peers: {
        InternalSelectMenu: internalSelectMenuDark,
        InternalSelection: internalSelectionDark,
        Scrollbar: scrollbarDark,
        Checkbox: checkboxDark,
        Empty: emptyLight
      },
      self: self$12
    };
    const codeDark = {
      name: "Code",
      common: derived$1,
      self(vars) {
        const {
          textColor2,
          fontSize: fontSize2,
          fontWeightStrong,
          textColor3
        } = vars;
        return {
          textColor: textColor2,
          fontSize: fontSize2,
          fontWeightStrong,
          "mono-3": "#5c6370",
          "hue-1": "#56b6c2",
          "hue-2": "#61aeee",
          "hue-3": "#c678dd",
          "hue-4": "#98c379",
          "hue-5": "#e06c75",
          "hue-5-2": "#be5046",
          "hue-6": "#d19a66",
          "hue-6-2": "#e6c07b",
          lineNumberTextColor: textColor3
        };
      }
    };
    function self$11(vars) {
      const {
        textColor2,
        fontSize: fontSize2,
        fontWeightStrong,
        textColor3
      } = vars;
      return {
        textColor: textColor2,
        fontSize: fontSize2,
        fontWeightStrong,
        "mono-3": "#a0a1a7",
        "hue-1": "#0184bb",
        "hue-2": "#4078f2",
        "hue-3": "#a626a4",
        "hue-4": "#50a14f",
        "hue-5": "#e45649",
        "hue-5-2": "#c91243",
        "hue-6": "#986801",
        "hue-6-2": "#c18401",
        lineNumberTextColor: textColor3
      };
    }
    const codeLight = {
      name: "Code",
      common: derived,
      self: self$11
    };
    function self$10(vars) {
      const {
        fontWeight,
        textColor1,
        textColor2,
        textColorDisabled,
        dividerColor,
        fontSize: fontSize2
      } = vars;
      return {
        titleFontSize: fontSize2,
        titleFontWeight: fontWeight,
        dividerColor,
        titleTextColor: textColor1,
        titleTextColorDisabled: textColorDisabled,
        fontSize: fontSize2,
        textColor: textColor2,
        arrowColor: textColor2,
        arrowColorDisabled: textColorDisabled,
        itemMargin: "16px 0 0 0",
        titlePadding: "16px 0 0 0"
      };
    }
    const collapseLight = {
      name: "Collapse",
      common: derived,
      self: self$10
    };
    const collapseDark = {
      name: "Collapse",
      common: derived$1,
      self: self$10
    };
    function self$$(vars) {
      const {
        cubicBezierEaseInOut: cubicBezierEaseInOut2
      } = vars;
      return {
        bezier: cubicBezierEaseInOut2
      };
    }
    const collapseTransitionLight = {
      name: "CollapseTransition",
      common: derived,
      self: self$$
    };
    function self$_(vars) {
      const {
        fontSize: fontSize2,
        boxShadow2,
        popoverColor,
        textColor2,
        borderRadius,
        borderColor,
        heightSmall,
        heightMedium,
        heightLarge,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        dividerColor
      } = vars;
      return {
        panelFontSize: fontSize2,
        boxShadow: boxShadow2,
        color: popoverColor,
        textColor: textColor2,
        borderRadius,
        border: `1px solid ${borderColor}`,
        heightSmall,
        heightMedium,
        heightLarge,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        dividerColor
      };
    }
    const colorPickerLight = createTheme({
      name: "ColorPicker",
      common: derived,
      peers: {
        Input: inputLight,
        Button: buttonLight
      },
      self: self$_
    });
    const configProviderProps = {
      abstract: Boolean,
      bordered: {
        type: Boolean,
        default: void 0
      },
      clsPrefix: String,
      locale: Object,
      dateLocale: Object,
      namespace: String,
      rtl: Array,
      tag: {
        type: String,
        default: "div"
      },
      hljs: Object,
      katex: Object,
      theme: Object,
      themeOverrides: Object,
      componentOptions: Object,
      icons: Object,
      breakpoints: Object,
      preflightStyleDisabled: Boolean,
      styleMountTarget: Object,
      inlineThemeDisabled: {
        type: Boolean,
        default: void 0
      },
      as: {
        type: String,
        validator: () => {
          warn("config-provider", "`as` is deprecated, please use `tag` instead.");
          return true;
        },
        default: void 0
      }
    };
    var ConfigProvider_default = /* @__PURE__ */ defineComponent({
      name: "ConfigProvider",
      alias: ["App"],
      props: configProviderProps,
      setup(props) {
        const NConfigProvider = inject(configProviderInjectionKey, null);
        const mergedThemeRef = computed(() => {
          const {
            theme
          } = props;
          if (theme === null) return void 0;
          const inheritedTheme = NConfigProvider?.mergedThemeRef.value;
          return theme === void 0 ? inheritedTheme : inheritedTheme === void 0 ? theme : Object.assign({}, inheritedTheme, theme);
        });
        const mergedThemeOverridesRef = computed(() => {
          const {
            themeOverrides
          } = props;
          if (themeOverrides === null) return void 0;
          if (themeOverrides === void 0) return NConfigProvider?.mergedThemeOverridesRef.value;
          else {
            const inheritedThemeOverrides = NConfigProvider?.mergedThemeOverridesRef.value;
            if (inheritedThemeOverrides === void 0) return themeOverrides;
            else return merge({}, inheritedThemeOverrides, themeOverrides);
          }
        });
        const mergedNamespaceRef = useMemo(() => {
          const {
            namespace
          } = props;
          return namespace === void 0 ? NConfigProvider?.mergedNamespaceRef.value : namespace;
        });
        const mergedBorderedRef = useMemo(() => {
          const {
            bordered
          } = props;
          return bordered === void 0 ? NConfigProvider?.mergedBorderedRef.value : bordered;
        });
        const mergedIconsRef = computed(() => {
          const {
            icons
          } = props;
          return icons === void 0 ? NConfigProvider?.mergedIconsRef.value : icons;
        });
        const mergedComponentPropsRef = computed(() => {
          const {
            componentOptions
          } = props;
          if (componentOptions !== void 0) return componentOptions;
          return NConfigProvider?.mergedComponentPropsRef.value;
        });
        const mergedClsPrefixRef = computed(() => {
          const {
            clsPrefix
          } = props;
          if (clsPrefix !== void 0) return clsPrefix;
          if (NConfigProvider) return NConfigProvider.mergedClsPrefixRef.value;
          return "n";
        });
        const mergedRtlRef = computed(() => {
          const {
            rtl
          } = props;
          if (rtl === void 0) return NConfigProvider?.mergedRtlRef.value;
          const rtlEnabledState = {};
          for (const rtlInfo of rtl) {
            rtlEnabledState[rtlInfo.name] = markRaw(rtlInfo);
            rtlInfo.peers?.forEach((peerRtlInfo) => {
              if (!(peerRtlInfo.name in rtlEnabledState)) rtlEnabledState[peerRtlInfo.name] = markRaw(peerRtlInfo);
            });
          }
          return rtlEnabledState;
        });
        const mergedBreakpointsRef = computed(() => {
          return props.breakpoints || NConfigProvider?.mergedBreakpointsRef.value;
        });
        const inlineThemeDisabled = props.inlineThemeDisabled || NConfigProvider?.inlineThemeDisabled;
        const preflightStyleDisabled = props.preflightStyleDisabled || NConfigProvider?.preflightStyleDisabled;
        const styleMountTarget = props.styleMountTarget || NConfigProvider?.styleMountTarget;
        const mergedThemeHashRef = computed(() => {
          const {
            value: theme
          } = mergedThemeRef;
          const {
            value: mergedThemeOverrides
          } = mergedThemeOverridesRef;
          const hasThemeOverrides = mergedThemeOverrides && Object.keys(mergedThemeOverrides).length !== 0;
          const themeName = theme?.name;
          if (themeName) {
            if (hasThemeOverrides) return `${themeName}-${murmur2(JSON.stringify(mergedThemeOverridesRef.value))}`;
            return themeName;
          } else {
            if (hasThemeOverrides) return murmur2(JSON.stringify(mergedThemeOverridesRef.value));
            return "";
          }
        });
        provide(configProviderInjectionKey, {
          mergedThemeHashRef,
          mergedBreakpointsRef,
          mergedRtlRef,
          mergedIconsRef,
          mergedComponentPropsRef,
          mergedBorderedRef,
          mergedNamespaceRef,
          mergedClsPrefixRef,
          mergedLocaleRef: computed(() => {
            const {
              locale
            } = props;
            if (locale === null) return void 0;
            return locale === void 0 ? NConfigProvider?.mergedLocaleRef.value : locale;
          }),
          mergedDateLocaleRef: computed(() => {
            const {
              dateLocale
            } = props;
            if (dateLocale === null) return void 0;
            return dateLocale === void 0 ? NConfigProvider?.mergedDateLocaleRef.value : dateLocale;
          }),
          mergedHljsRef: computed(() => {
            const {
              hljs
            } = props;
            return hljs === void 0 ? NConfigProvider?.mergedHljsRef.value : hljs;
          }),
          mergedKatexRef: computed(() => {
            const {
              katex
            } = props;
            return katex === void 0 ? NConfigProvider?.mergedKatexRef.value : katex;
          }),
          mergedThemeRef,
          mergedThemeOverridesRef,
          inlineThemeDisabled: inlineThemeDisabled || false,
          preflightStyleDisabled: preflightStyleDisabled || false,
          styleMountTarget
        });
        return {
          mergedClsPrefix: mergedClsPrefixRef,
          mergedBordered: mergedBorderedRef,
          mergedNamespace: mergedNamespaceRef,
          mergedTheme: mergedThemeRef,
          mergedThemeOverrides: mergedThemeOverridesRef
        };
      },
      render() {
        return !this.abstract ? h(this.as || this.tag, {
          class: `${this.mergedClsPrefix || "n"}-config-provider`
        }, this.$slots.default?.()) : this.$slots.default?.();
      }
    });
    const popselect = {
      name: "Popselect",
      common: derived$1,
      peers: {
        Popover: popoverDark,
        InternalSelectMenu: internalSelectMenuDark
      }
    };
    function self$Z(vars) {
      const {
        boxShadow2
      } = vars;
      return {
        menuBoxShadow: boxShadow2
      };
    }
    const popselectLight = createTheme({
      name: "Popselect",
      common: derived,
      peers: {
        Popover: popoverLight,
        InternalSelectMenu: internalSelectMenuLight
      },
      self: self$Z
    });
    function self$Y(vars) {
      const {
        boxShadow2
      } = vars;
      return {
        menuBoxShadow: boxShadow2
      };
    }
    const selectLight = createTheme({
      name: "Select",
      common: derived,
      peers: {
        InternalSelection: internalSelectionLight,
        InternalSelectMenu: internalSelectMenuLight
      },
      self: self$Y
    });
    const selectDark = {
      name: "Select",
      common: derived$1,
      peers: {
        InternalSelection: internalSelectionDark,
        InternalSelectMenu: internalSelectMenuDark
      },
      self: self$Y
    };
    var _common_default$q = {
      itemPaddingSmall: "0 4px",
      itemMarginSmall: "0 0 0 8px",
      itemMarginSmallRtl: "0 8px 0 0",
      itemPaddingMedium: "0 4px",
      itemMarginMedium: "0 0 0 8px",
      itemMarginMediumRtl: "0 8px 0 0",
      itemPaddingLarge: "0 4px",
      itemMarginLarge: "0 0 0 8px",
      itemMarginLargeRtl: "0 8px 0 0",
      buttonIconSizeSmall: "14px",
      buttonIconSizeMedium: "16px",
      buttonIconSizeLarge: "18px",
      inputWidthSmall: "60px",
      selectWidthSmall: "unset",
      inputMarginSmall: "0 0 0 8px",
      inputMarginSmallRtl: "0 8px 0 0",
      selectMarginSmall: "0 0 0 8px",
      prefixMarginSmall: "0 8px 0 0",
      suffixMarginSmall: "0 0 0 8px",
      inputWidthMedium: "60px",
      selectWidthMedium: "unset",
      inputMarginMedium: "0 0 0 8px",
      inputMarginMediumRtl: "0 8px 0 0",
      selectMarginMedium: "0 0 0 8px",
      prefixMarginMedium: "0 8px 0 0",
      suffixMarginMedium: "0 0 0 8px",
      inputWidthLarge: "60px",
      selectWidthLarge: "unset",
      inputMarginLarge: "0 0 0 8px",
      inputMarginLargeRtl: "0 8px 0 0",
      selectMarginLarge: "0 0 0 8px",
      prefixMarginLarge: "0 8px 0 0",
      suffixMarginLarge: "0 0 0 8px"
    };
    function self$X(vars) {
      const {
        textColor2,
        primaryColor,
        primaryColorHover,
        primaryColorPressed,
        inputColorDisabled,
        textColorDisabled,
        borderColor,
        borderRadius,
        fontSizeTiny,
        fontSizeSmall,
        fontSizeMedium,
        heightTiny,
        heightSmall,
        heightMedium
      } = vars;
      return {
        ..._common_default$q,
        buttonColor: "#0000",
        buttonColorHover: "#0000",
        buttonColorPressed: "#0000",
        buttonBorder: `1px solid ${borderColor}`,
        buttonBorderHover: `1px solid ${borderColor}`,
        buttonBorderPressed: `1px solid ${borderColor}`,
        buttonIconColor: textColor2,
        buttonIconColorHover: textColor2,
        buttonIconColorPressed: textColor2,
        itemTextColor: textColor2,
        itemTextColorHover: primaryColorHover,
        itemTextColorPressed: primaryColorPressed,
        itemTextColorActive: primaryColor,
        itemTextColorDisabled: textColorDisabled,
        itemColor: "#0000",
        itemColorHover: "#0000",
        itemColorPressed: "#0000",
        itemColorActive: "#0000",
        itemColorActiveHover: "#0000",
        itemColorDisabled: inputColorDisabled,
        itemBorder: "1px solid #0000",
        itemBorderHover: "1px solid #0000",
        itemBorderPressed: "1px solid #0000",
        itemBorderActive: `1px solid ${primaryColor}`,
        itemBorderDisabled: `1px solid ${borderColor}`,
        itemBorderRadius: borderRadius,
        itemSizeSmall: heightTiny,
        itemSizeMedium: heightSmall,
        itemSizeLarge: heightMedium,
        itemFontSizeSmall: fontSizeTiny,
        itemFontSizeMedium: fontSizeSmall,
        itemFontSizeLarge: fontSizeMedium,
        jumperFontSizeSmall: fontSizeTiny,
        jumperFontSizeMedium: fontSizeSmall,
        jumperFontSizeLarge: fontSizeMedium,
        jumperTextColor: textColor2,
        jumperTextColorDisabled: textColorDisabled
      };
    }
    const paginationLight = createTheme({
      name: "Pagination",
      common: derived,
      peers: {
        Select: selectLight,
        Input: inputLight,
        Popselect: popselectLight
      },
      self: self$X
    });
    const paginationDark = {
      name: "Pagination",
      common: derived$1,
      peers: {
        Select: selectDark,
        Input: inputDark,
        Popselect: popselect
      },
      self(vars) {
        const {
          primaryColor,
          opacity3
        } = vars;
        const borderColorActive = changeColor(primaryColor, {
          alpha: Number(opacity3)
        });
        const commonSelf = self$X(vars);
        commonSelf.itemBorderActive = `1px solid ${borderColorActive}`;
        commonSelf.itemBorderDisabled = "1px solid #0000";
        return commonSelf;
      }
    };
    var _common_default$p = {
      padding: "4px 0",
      optionIconSizeSmall: "14px",
      optionIconSizeMedium: "16px",
      optionIconSizeLarge: "16px",
      optionIconSizeHuge: "18px",
      optionSuffixWidthSmall: "14px",
      optionSuffixWidthMedium: "14px",
      optionSuffixWidthLarge: "16px",
      optionSuffixWidthHuge: "16px",
      optionIconSuffixWidthSmall: "32px",
      optionIconSuffixWidthMedium: "32px",
      optionIconSuffixWidthLarge: "36px",
      optionIconSuffixWidthHuge: "36px",
      optionPrefixWidthSmall: "14px",
      optionPrefixWidthMedium: "14px",
      optionPrefixWidthLarge: "16px",
      optionPrefixWidthHuge: "16px",
      optionIconPrefixWidthSmall: "36px",
      optionIconPrefixWidthMedium: "36px",
      optionIconPrefixWidthLarge: "40px",
      optionIconPrefixWidthHuge: "40px"
    };
    function self$W(vars) {
      const {
        primaryColor,
        textColor2,
        dividerColor,
        hoverColor,
        popoverColor,
        invertedColor,
        borderRadius,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        fontSizeHuge,
        heightSmall,
        heightMedium,
        heightLarge,
        heightHuge,
        textColor3,
        opacityDisabled
      } = vars;
      return {
        ..._common_default$p,
        optionHeightSmall: heightSmall,
        optionHeightMedium: heightMedium,
        optionHeightLarge: heightLarge,
        optionHeightHuge: heightHuge,
        borderRadius,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        fontSizeHuge,
        optionTextColor: textColor2,
        optionTextColorHover: textColor2,
        optionTextColorActive: primaryColor,
        optionTextColorChildActive: primaryColor,
        color: popoverColor,
        dividerColor,
        suffixColor: textColor2,
        prefixColor: textColor2,
        optionColorHover: hoverColor,
        optionColorActive: changeColor(primaryColor, {
          alpha: 0.1
        }),
        groupHeaderTextColor: textColor3,
        optionTextColorInverted: "#BBB",
        optionTextColorHoverInverted: "#FFF",
        optionTextColorActiveInverted: "#FFF",
        optionTextColorChildActiveInverted: "#FFF",
        colorInverted: invertedColor,
        dividerColorInverted: "#BBB",
        suffixColorInverted: "#BBB",
        prefixColorInverted: "#BBB",
        optionColorHoverInverted: primaryColor,
        optionColorActiveInverted: primaryColor,
        groupHeaderTextColorInverted: "#AAA",
        optionOpacityDisabled: opacityDisabled
      };
    }
    const dropdownLight = createTheme({
      name: "Dropdown",
      common: derived,
      peers: {
        Popover: popoverLight
      },
      self: self$W
    });
    const dropdownDark = {
      name: "Dropdown",
      common: derived$1,
      peers: {
        Popover: popoverDark
      },
      self(vars) {
        const {
          primaryColorSuppl,
          primaryColor,
          popoverColor
        } = vars;
        const commonSelf = self$W(vars);
        commonSelf.colorInverted = popoverColor;
        commonSelf.optionColorActive = changeColor(primaryColor, {
          alpha: 0.15
        });
        commonSelf.optionColorActiveInverted = primaryColorSuppl;
        commonSelf.optionColorHoverInverted = primaryColorSuppl;
        return commonSelf;
      }
    };
    var _common_default$o = {
      padding: "8px 14px"
    };
    const tooltipDark = {
      name: "Tooltip",
      common: derived$1,
      peers: {
        Popover: popoverDark
      },
      self(vars) {
        const {
          borderRadius,
          boxShadow2,
          popoverColor,
          textColor2
        } = vars;
        return {
          ..._common_default$o,
          borderRadius,
          boxShadow: boxShadow2,
          color: popoverColor,
          textColor: textColor2
        };
      }
    };
    var _common_default$n = {
      radioSizeSmall: "14px",
      radioSizeMedium: "16px",
      radioSizeLarge: "18px",
      labelPadding: "0 8px",
      labelFontWeight: "400"
    };
    const radioDark = {
      name: "Radio",
      common: derived$1,
      self(vars) {
        const {
          borderColor,
          primaryColor,
          baseColor,
          textColorDisabled,
          inputColorDisabled,
          textColor2,
          opacityDisabled,
          borderRadius,
          fontSizeSmall,
          fontSizeMedium,
          fontSizeLarge,
          heightSmall,
          heightMedium,
          heightLarge,
          lineHeight: lineHeight2
        } = vars;
        return {
          ..._common_default$n,
          labelLineHeight: lineHeight2,
          buttonHeightSmall: heightSmall,
          buttonHeightMedium: heightMedium,
          buttonHeightLarge: heightLarge,
          fontSizeSmall,
          fontSizeMedium,
          fontSizeLarge,
          boxShadow: `inset 0 0 0 1px ${borderColor}`,
          boxShadowActive: `inset 0 0 0 1px ${primaryColor}`,
          boxShadowFocus: `inset 0 0 0 1px ${primaryColor}, 0 0 0 2px ${changeColor(primaryColor, {
            alpha: 0.3
          })}`,
          boxShadowHover: `inset 0 0 0 1px ${primaryColor}`,
          boxShadowDisabled: `inset 0 0 0 1px ${borderColor}`,
          color: "#0000",
          colorDisabled: inputColorDisabled,
          colorActive: "#0000",
          textColor: textColor2,
          textColorDisabled,
          dotColorActive: primaryColor,
          dotColorDisabled: borderColor,
          buttonBorderColor: borderColor,
          buttonBorderColorActive: primaryColor,
          buttonBorderColorHover: primaryColor,
          buttonColor: "#0000",
          buttonColorActive: primaryColor,
          buttonTextColor: textColor2,
          buttonTextColorActive: baseColor,
          buttonTextColorHover: primaryColor,
          opacityDisabled,
          buttonBoxShadowFocus: `inset 0 0 0 1px ${primaryColor}, 0 0 0 2px ${changeColor(primaryColor, {
            alpha: 0.3
          })}`,
          buttonBoxShadowHover: `inset 0 0 0 1px ${primaryColor}`,
          buttonBoxShadow: "inset 0 0 0 1px #0000",
          buttonBorderRadius: borderRadius
        };
      }
    };
    const ellipsisDark = {
      name: "Ellipsis",
      common: derived$1,
      peers: {
        Tooltip: tooltipDark
      }
    };
    function self$V(vars) {
      const {
        borderRadius,
        boxShadow2,
        baseColor
      } = vars;
      return {
        ..._common_default$o,
        borderRadius,
        boxShadow: boxShadow2,
        color: composite(baseColor, "rgba(0, 0, 0, .85)"),
        textColor: baseColor
      };
    }
    const tooltipLight = createTheme({
      name: "Tooltip",
      common: derived,
      peers: {
        Popover: popoverLight
      },
      self: self$V
    });
    const ellipsisLight = createTheme({
      name: "Ellipsis",
      common: derived,
      peers: {
        Tooltip: tooltipLight
      }
    });
    function self$U(vars) {
      const {
        borderColor,
        primaryColor,
        baseColor,
        textColorDisabled,
        inputColorDisabled,
        textColor2,
        opacityDisabled,
        borderRadius,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        heightSmall,
        heightMedium,
        heightLarge,
        lineHeight: lineHeight2
      } = vars;
      return {
        ..._common_default$n,
        labelLineHeight: lineHeight2,
        buttonHeightSmall: heightSmall,
        buttonHeightMedium: heightMedium,
        buttonHeightLarge: heightLarge,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        boxShadow: `inset 0 0 0 1px ${borderColor}`,
        boxShadowActive: `inset 0 0 0 1px ${primaryColor}`,
        boxShadowFocus: `inset 0 0 0 1px ${primaryColor}, 0 0 0 2px ${changeColor(primaryColor, {
          alpha: 0.2
        })}`,
        boxShadowHover: `inset 0 0 0 1px ${primaryColor}`,
        boxShadowDisabled: `inset 0 0 0 1px ${borderColor}`,
        color: baseColor,
        colorDisabled: inputColorDisabled,
        colorActive: "#0000",
        textColor: textColor2,
        textColorDisabled,
        dotColorActive: primaryColor,
        dotColorDisabled: borderColor,
        buttonBorderColor: borderColor,
        buttonBorderColorActive: primaryColor,
        buttonBorderColorHover: borderColor,
        buttonColor: baseColor,
        buttonColorActive: baseColor,
        buttonTextColor: textColor2,
        buttonTextColorActive: primaryColor,
        buttonTextColorHover: primaryColor,
        opacityDisabled,
        buttonBoxShadowFocus: `inset 0 0 0 1px ${primaryColor}, 0 0 0 2px ${changeColor(primaryColor, {
          alpha: 0.3
        })}`,
        buttonBoxShadowHover: "inset 0 0 0 1px #0000",
        buttonBoxShadow: "inset 0 0 0 1px #0000",
        buttonBorderRadius: borderRadius
      };
    }
    const radioLight = {
      name: "Radio",
      common: derived,
      self: self$U
    };
    var _common_default$m = {
      thPaddingSmall: "8px",
      thPaddingMedium: "12px",
      thPaddingLarge: "12px",
      tdPaddingSmall: "8px",
      tdPaddingMedium: "12px",
      tdPaddingLarge: "12px",
      sorterSize: "15px",
      resizableContainerSize: "8px",
      resizableSize: "2px",
      filterSize: "15px",
      paginationMargin: "12px 0 0 0",
      emptyPadding: "48px 0",
      actionPadding: "8px 12px",
      actionButtonMargin: "0 8px 0 0"
    };
    function self$T(vars) {
      const {
        cardColor,
        modalColor,
        popoverColor,
        textColor2,
        textColor1,
        tableHeaderColor,
        tableColorHover,
        iconColor,
        primaryColor,
        fontWeightStrong,
        borderRadius,
        lineHeight: lineHeight2,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        dividerColor,
        heightSmall,
        opacityDisabled,
        tableColorStriped
      } = vars;
      return {
        ..._common_default$m,
        actionDividerColor: dividerColor,
        lineHeight: lineHeight2,
        borderRadius,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        borderColor: composite(cardColor, dividerColor),
        tdColorHover: composite(cardColor, tableColorHover),
        tdColorSorting: composite(cardColor, tableColorHover),
        tdColorStriped: composite(cardColor, tableColorStriped),
        thColor: composite(cardColor, tableHeaderColor),
        thColorHover: composite(composite(cardColor, tableHeaderColor), tableColorHover),
        thColorSorting: composite(composite(cardColor, tableHeaderColor), tableColorHover),
        tdColor: cardColor,
        tdTextColor: textColor2,
        thTextColor: textColor1,
        thFontWeight: fontWeightStrong,
        thButtonColorHover: tableColorHover,
        thIconColor: iconColor,
        thIconColorActive: primaryColor,
        borderColorModal: composite(modalColor, dividerColor),
        tdColorHoverModal: composite(modalColor, tableColorHover),
        tdColorSortingModal: composite(modalColor, tableColorHover),
        tdColorStripedModal: composite(modalColor, tableColorStriped),
        thColorModal: composite(modalColor, tableHeaderColor),
        thColorHoverModal: composite(composite(modalColor, tableHeaderColor), tableColorHover),
        thColorSortingModal: composite(composite(modalColor, tableHeaderColor), tableColorHover),
        tdColorModal: modalColor,
        borderColorPopover: composite(popoverColor, dividerColor),
        tdColorHoverPopover: composite(popoverColor, tableColorHover),
        tdColorSortingPopover: composite(popoverColor, tableColorHover),
        tdColorStripedPopover: composite(popoverColor, tableColorStriped),
        thColorPopover: composite(popoverColor, tableHeaderColor),
        thColorHoverPopover: composite(composite(popoverColor, tableHeaderColor), tableColorHover),
        thColorSortingPopover: composite(composite(popoverColor, tableHeaderColor), tableColorHover),
        tdColorPopover: popoverColor,
        boxShadowBefore: "inset -12px 0 8px -12px rgba(0, 0, 0, .18)",
        boxShadowAfter: "inset 12px 0 8px -12px rgba(0, 0, 0, .18)",
        loadingColor: primaryColor,
        loadingSize: heightSmall,
        opacityLoading: opacityDisabled
      };
    }
    const dataTableLight = createTheme({
      name: "DataTable",
      common: derived,
      peers: {
        Button: buttonLight,
        Checkbox: checkboxLight,
        Radio: radioLight,
        Pagination: paginationLight,
        Scrollbar: scrollbarLight,
        Empty: emptyLight,
        Popover: popoverLight,
        Ellipsis: ellipsisLight,
        Dropdown: dropdownLight
      },
      self: self$T
    });
    const dataTableDark = {
      name: "DataTable",
      common: derived$1,
      peers: {
        Button: buttonDark,
        Checkbox: checkboxDark,
        Radio: radioDark,
        Pagination: paginationDark,
        Scrollbar: scrollbarDark,
        Empty: emptyDark,
        Popover: popoverDark,
        Ellipsis: ellipsisDark,
        Dropdown: dropdownDark
      },
      self(vars) {
        const commonSelf = self$T(vars);
        commonSelf.boxShadowAfter = "inset 12px 0 8px -12px rgba(0, 0, 0, .36)";
        commonSelf.boxShadowBefore = "inset -12px 0 8px -12px rgba(0, 0, 0, .36)";
        return commonSelf;
      }
    };
    function self$S(vars) {
      const {
        textColorBase,
        opacity1,
        opacity2,
        opacity3,
        opacity4,
        opacity5
      } = vars;
      return {
        color: textColorBase,
        opacity1Depth: opacity1,
        opacity2Depth: opacity2,
        opacity3Depth: opacity3,
        opacity4Depth: opacity4,
        opacity5Depth: opacity5
      };
    }
    const iconLight = {
      name: "Icon",
      common: derived,
      self: self$S
    };
    const iconDark$1 = {
      name: "Icon",
      common: derived$1,
      self: self$S
    };
    var index_cssr_default$1 = cB("icon", `
 height: 1em;
 width: 1em;
 line-height: 1em;
 text-align: center;
 display: inline-block;
 position: relative;
 fill: currentColor;
`, [cM("color-transition", {
      transition: "color .3s var(--n-bezier)"
    }), cM("depth", {
      color: "var(--n-color)"
    }, [c("svg", {
      opacity: "var(--n-opacity)",
      transition: "opacity .3s var(--n-bezier)"
    })]), c("svg", {
      height: "1em",
      width: "1em"
    })]);
    const iconProps = {
      ...useTheme.props,
      depth: [String, Number],
      size: [Number, String],
      color: String,
      component: [Object, Function]
    };
    const NIcon = /* @__PURE__ */ defineComponent({
      _n_icon__: true,
      name: "Icon",
      inheritAttrs: false,
      props: iconProps,
      setup(props) {
        const {
          mergedClsPrefixRef,
          inlineThemeDisabled
        } = useConfig(props);
        const themeRef = useTheme("Icon", "-icon", index_cssr_default$1, iconLight, props, mergedClsPrefixRef);
        const cssVarsRef = computed(() => {
          const {
            depth
          } = props;
          const {
            common: {
              cubicBezierEaseInOut: cubicBezierEaseInOut2
            },
            self: self2
          } = themeRef.value;
          if (depth !== void 0) {
            const {
              color,
              [`opacity${depth}Depth`]: opacity
            } = self2;
            return {
              "--n-bezier": cubicBezierEaseInOut2,
              "--n-color": color,
              "--n-opacity": opacity
            };
          }
          return {
            "--n-bezier": cubicBezierEaseInOut2,
            "--n-color": "",
            "--n-opacity": ""
          };
        });
        const themeClassHandle = inlineThemeDisabled ? useThemeClass("icon", computed(() => `${props.depth || "d"}`), cssVarsRef, props) : void 0;
        return {
          mergedClsPrefix: mergedClsPrefixRef,
          mergedStyle: computed(() => {
            const {
              size,
              color
            } = props;
            return {
              fontSize: formatLength(size),
              color
            };
          }),
          cssVars: inlineThemeDisabled ? void 0 : cssVarsRef,
          themeClass: themeClassHandle?.themeClass,
          onRender: themeClassHandle?.onRender
        };
      },
      render() {
        const {
          $parent,
          depth,
          mergedClsPrefix,
          component,
          onRender,
          themeClass
        } = this;
        if ($parent?.$options?._n_icon__) warn("icon", "don't wrap `n-icon` inside `n-icon`");
        onRender?.();
        return h("i", mergeProps(this.$attrs, {
          role: "img",
          class: [`${mergedClsPrefix}-icon`, themeClass, {
            [`${mergedClsPrefix}-icon--depth`]: depth,
            [`${mergedClsPrefix}-icon--color-transition`]: depth !== void 0
          }],
          style: [this.cssVars, this.mergedStyle]
        }), component ? h(component) : this.$slots.default?.());
      }
    });
    var _common_default$l = {
      itemFontSize: "12px",
      itemHeight: "36px",
      itemWidth: "52px",
      panelActionPadding: "8px 0"
    };
    function self$R(vars) {
      const {
        popoverColor,
        textColor2,
        primaryColor,
        hoverColor,
        dividerColor,
        opacityDisabled,
        boxShadow2,
        borderRadius,
        iconColor,
        iconColorDisabled
      } = vars;
      return {
        ..._common_default$l,
        panelColor: popoverColor,
        panelBoxShadow: boxShadow2,
        panelDividerColor: dividerColor,
        itemTextColor: textColor2,
        itemTextColorActive: primaryColor,
        itemColorHover: hoverColor,
        itemOpacityDisabled: opacityDisabled,
        itemBorderRadius: borderRadius,
        borderRadius,
        iconColor,
        iconColorDisabled
      };
    }
    const timePickerLight = createTheme({
      name: "TimePicker",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight,
        Button: buttonLight,
        Input: inputLight
      },
      self: self$R
    });
    const timePickerDark = {
      name: "TimePicker",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark,
        Button: buttonDark,
        Input: inputDark
      },
      self: self$R
    };
    var _common_default$k = {
      itemSize: "24px",
      itemCellWidth: "38px",
      itemCellHeight: "32px",
      scrollItemWidth: "80px",
      scrollItemHeight: "40px",
      panelExtraFooterPadding: "8px 12px",
      panelActionPadding: "8px 12px",
      calendarTitlePadding: "0",
      calendarTitleHeight: "28px",
      arrowSize: "14px",
      panelHeaderPadding: "8px 12px",
      calendarDaysHeight: "32px",
      calendarTitleGridTempateColumns: "28px 28px 1fr 28px 28px",
      calendarLeftPaddingDate: "6px 12px 4px 12px",
      calendarLeftPaddingDatetime: "4px 12px",
      calendarLeftPaddingDaterange: "6px 12px 4px 12px",
      calendarLeftPaddingDatetimerange: "4px 12px",
      calendarLeftPaddingMonth: "0",
      calendarLeftPaddingYear: "0",
      calendarLeftPaddingQuarter: "0",
      calendarLeftPaddingMonthrange: "0",
      calendarLeftPaddingQuarterrange: "0",
      calendarLeftPaddingYearrange: "0",
      calendarLeftPaddingWeek: "6px 12px 4px 12px",
      calendarRightPaddingDate: "6px 12px 4px 12px",
      calendarRightPaddingDatetime: "4px 12px",
      calendarRightPaddingDaterange: "6px 12px 4px 12px",
      calendarRightPaddingDatetimerange: "4px 12px",
      calendarRightPaddingMonth: "0",
      calendarRightPaddingYear: "0",
      calendarRightPaddingQuarter: "0",
      calendarRightPaddingMonthrange: "0",
      calendarRightPaddingQuarterrange: "0",
      calendarRightPaddingYearrange: "0",
      calendarRightPaddingWeek: "0"
    };
    function self$Q(vars) {
      const {
        hoverColor,
        fontSize: fontSize2,
        textColor2,
        textColorDisabled,
        popoverColor,
        primaryColor,
        borderRadiusSmall,
        iconColor,
        iconColorDisabled,
        textColor1,
        dividerColor,
        boxShadow2,
        borderRadius,
        fontWeightStrong
      } = vars;
      return {
        ..._common_default$k,
        itemFontSize: fontSize2,
        calendarDaysFontSize: fontSize2,
        calendarTitleFontSize: fontSize2,
        itemTextColor: textColor2,
        itemTextColorDisabled: textColorDisabled,
        itemTextColorActive: popoverColor,
        itemTextColorCurrent: primaryColor,
        itemColorIncluded: changeColor(primaryColor, {
          alpha: 0.1
        }),
        itemColorHover: hoverColor,
        itemColorDisabled: hoverColor,
        itemColorActive: primaryColor,
        itemBorderRadius: borderRadiusSmall,
        panelColor: popoverColor,
        panelTextColor: textColor2,
        arrowColor: iconColor,
        calendarTitleTextColor: textColor1,
        calendarTitleColorHover: hoverColor,
        calendarDaysTextColor: textColor2,
        panelHeaderDividerColor: dividerColor,
        calendarDaysDividerColor: dividerColor,
        calendarDividerColor: dividerColor,
        panelActionDividerColor: dividerColor,
        panelBoxShadow: boxShadow2,
        panelBorderRadius: borderRadius,
        calendarTitleFontWeight: fontWeightStrong,
        scrollItemBorderRadius: borderRadius,
        iconColor,
        iconColorDisabled
      };
    }
    const datePickerLight = createTheme({
      name: "DatePicker",
      common: derived,
      peers: {
        Input: inputLight,
        Button: buttonLight,
        TimePicker: timePickerLight,
        Scrollbar: scrollbarLight
      },
      self: self$Q
    });
    const datePickerDark = {
      name: "DatePicker",
      common: derived$1,
      peers: {
        Input: inputDark,
        Button: buttonDark,
        TimePicker: timePickerDark,
        Scrollbar: scrollbarDark
      },
      self(vars) {
        const {
          popoverColor,
          hoverColor,
          primaryColor
        } = vars;
        const commonSelf = self$Q(vars);
        commonSelf.itemColorDisabled = composite(popoverColor, hoverColor);
        commonSelf.itemColorIncluded = changeColor(primaryColor, {
          alpha: 0.15
        });
        commonSelf.itemColorHover = composite(popoverColor, hoverColor);
        return commonSelf;
      }
    };
    var _common_default$j = {
      thPaddingBorderedSmall: "8px 12px",
      thPaddingBorderedMedium: "12px 16px",
      thPaddingBorderedLarge: "16px 24px",
      thPaddingSmall: "0",
      thPaddingMedium: "0",
      thPaddingLarge: "0",
      tdPaddingBorderedSmall: "8px 12px",
      tdPaddingBorderedMedium: "12px 16px",
      tdPaddingBorderedLarge: "16px 24px",
      tdPaddingSmall: "0 0 8px 0",
      tdPaddingMedium: "0 0 12px 0",
      tdPaddingLarge: "0 0 16px 0"
    };
    function self$P(vars) {
      const {
        tableHeaderColor,
        textColor2,
        textColor1,
        cardColor,
        modalColor,
        popoverColor,
        dividerColor,
        borderRadius,
        fontWeightStrong,
        lineHeight: lineHeight2,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge
      } = vars;
      return {
        ..._common_default$j,
        lineHeight: lineHeight2,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        titleTextColor: textColor1,
        thColor: composite(cardColor, tableHeaderColor),
        thColorModal: composite(modalColor, tableHeaderColor),
        thColorPopover: composite(popoverColor, tableHeaderColor),
        thTextColor: textColor1,
        thFontWeight: fontWeightStrong,
        tdTextColor: textColor2,
        tdColor: cardColor,
        tdColorModal: modalColor,
        tdColorPopover: popoverColor,
        borderColor: composite(cardColor, dividerColor),
        borderColorModal: composite(modalColor, dividerColor),
        borderColorPopover: composite(popoverColor, dividerColor),
        borderRadius
      };
    }
    const descriptionsLight = {
      name: "Descriptions",
      common: derived,
      self: self$P
    };
    const descriptionsDark = {
      name: "Descriptions",
      common: derived$1,
      self: self$P
    };
    var _common_default$i = {
      titleFontSize: "18px",
      padding: "16px 28px 20px 28px",
      iconSize: "28px",
      actionSpace: "12px",
      contentMargin: "8px 0 16px 0",
      iconMargin: "0 4px 0 0",
      iconMarginIconTop: "4px 0 8px 0",
      closeSize: "22px",
      closeIconSize: "18px",
      closeMargin: "20px 26px 0 0",
      closeMarginIconTop: "10px 16px 0 0"
    };
    function self$O(vars) {
      const {
        textColor1,
        textColor2,
        modalColor,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeColorHover,
        closeColorPressed,
        infoColor,
        successColor,
        warningColor,
        errorColor,
        primaryColor,
        dividerColor,
        borderRadius,
        fontWeightStrong,
        lineHeight: lineHeight2,
        fontSize: fontSize2
      } = vars;
      return {
        ..._common_default$i,
        fontSize: fontSize2,
        lineHeight: lineHeight2,
        border: `1px solid ${dividerColor}`,
        titleTextColor: textColor1,
        textColor: textColor2,
        color: modalColor,
        closeColorHover,
        closeColorPressed,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeBorderRadius: borderRadius,
        iconColor: primaryColor,
        iconColorInfo: infoColor,
        iconColorSuccess: successColor,
        iconColorWarning: warningColor,
        iconColorError: errorColor,
        borderRadius,
        titleFontWeight: fontWeightStrong
      };
    }
    const dialogLight = createTheme({
      name: "Dialog",
      common: derived,
      peers: {
        Button: buttonLight
      },
      self: self$O
    });
    const dialogDark = {
      name: "Dialog",
      common: derived$1,
      peers: {
        Button: buttonDark
      },
      self: self$O
    };
    function self$N(vars) {
      const {
        modalColor,
        textColor2,
        boxShadow3
      } = vars;
      return {
        color: modalColor,
        textColor: textColor2,
        boxShadow: boxShadow3
      };
    }
    const modalLight = createTheme({
      name: "Modal",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight,
        Dialog: dialogLight,
        Card: cardLight
      },
      self: self$N
    });
    const modalDark = {
      name: "Modal",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark,
        Dialog: dialogDark,
        Card: cardDark
      },
      self: self$N
    };
    const loadingBarDark = {
      name: "LoadingBar",
      common: derived$1,
      self(vars) {
        const {
          primaryColor
        } = vars;
        return {
          colorError: "red",
          colorLoading: primaryColor,
          height: "2px"
        };
      }
    };
    function self$M(vars) {
      const {
        primaryColor,
        errorColor
      } = vars;
      return {
        colorError: errorColor,
        colorLoading: primaryColor,
        height: "2px"
      };
    }
    const loadingBarLight = {
      name: "LoadingBar",
      common: derived,
      self: self$M
    };
    var _common_default$h = {
      margin: "0 0 8px 0",
      padding: "10px 20px",
      maxWidth: "720px",
      minWidth: "420px",
      iconMargin: "0 10px 0 0",
      closeMargin: "0 0 0 10px",
      closeSize: "20px",
      closeIconSize: "16px",
      iconSize: "20px",
      fontSize: "14px"
    };
    function self$L(vars) {
      const {
        textColor2,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        infoColor,
        successColor,
        errorColor,
        warningColor,
        popoverColor,
        boxShadow2,
        primaryColor,
        lineHeight: lineHeight2,
        borderRadius,
        closeColorHover,
        closeColorPressed
      } = vars;
      return {
        ..._common_default$h,
        closeBorderRadius: borderRadius,
        textColor: textColor2,
        textColorInfo: textColor2,
        textColorSuccess: textColor2,
        textColorError: textColor2,
        textColorWarning: textColor2,
        textColorLoading: textColor2,
        color: popoverColor,
        colorInfo: popoverColor,
        colorSuccess: popoverColor,
        colorError: popoverColor,
        colorWarning: popoverColor,
        colorLoading: popoverColor,
        boxShadow: boxShadow2,
        boxShadowInfo: boxShadow2,
        boxShadowSuccess: boxShadow2,
        boxShadowError: boxShadow2,
        boxShadowWarning: boxShadow2,
        boxShadowLoading: boxShadow2,
        iconColor: textColor2,
        iconColorInfo: infoColor,
        iconColorSuccess: successColor,
        iconColorWarning: warningColor,
        iconColorError: errorColor,
        iconColorLoading: primaryColor,
        closeColorHover,
        closeColorPressed,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeColorHoverInfo: closeColorHover,
        closeColorPressedInfo: closeColorPressed,
        closeIconColorInfo: closeIconColor,
        closeIconColorHoverInfo: closeIconColorHover,
        closeIconColorPressedInfo: closeIconColorPressed,
        closeColorHoverSuccess: closeColorHover,
        closeColorPressedSuccess: closeColorPressed,
        closeIconColorSuccess: closeIconColor,
        closeIconColorHoverSuccess: closeIconColorHover,
        closeIconColorPressedSuccess: closeIconColorPressed,
        closeColorHoverError: closeColorHover,
        closeColorPressedError: closeColorPressed,
        closeIconColorError: closeIconColor,
        closeIconColorHoverError: closeIconColorHover,
        closeIconColorPressedError: closeIconColorPressed,
        closeColorHoverWarning: closeColorHover,
        closeColorPressedWarning: closeColorPressed,
        closeIconColorWarning: closeIconColor,
        closeIconColorHoverWarning: closeIconColorHover,
        closeIconColorPressedWarning: closeIconColorPressed,
        closeColorHoverLoading: closeColorHover,
        closeColorPressedLoading: closeColorPressed,
        closeIconColorLoading: closeIconColor,
        closeIconColorHoverLoading: closeIconColorHover,
        closeIconColorPressedLoading: closeIconColorPressed,
        loadingColor: primaryColor,
        lineHeight: lineHeight2,
        borderRadius,
        border: "0"
      };
    }
    const messageLight = {
      name: "Message",
      common: derived,
      self: self$L
    };
    const messageDark = {
      name: "Message",
      common: derived$1,
      self: self$L
    };
    var _common_default$g = {
      closeMargin: "16px 12px",
      closeSize: "20px",
      closeIconSize: "16px",
      width: "365px",
      padding: "16px",
      titleFontSize: "16px",
      metaFontSize: "12px",
      descriptionFontSize: "12px"
    };
    function self$K(vars) {
      const {
        textColor2,
        successColor,
        infoColor,
        warningColor,
        errorColor,
        popoverColor,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeColorHover,
        closeColorPressed,
        textColor1,
        textColor3,
        borderRadius,
        fontWeightStrong,
        boxShadow2,
        lineHeight: lineHeight2,
        fontSize: fontSize2
      } = vars;
      return {
        ..._common_default$g,
        borderRadius,
        lineHeight: lineHeight2,
        fontSize: fontSize2,
        headerFontWeight: fontWeightStrong,
        iconColor: textColor2,
        iconColorSuccess: successColor,
        iconColorInfo: infoColor,
        iconColorWarning: warningColor,
        iconColorError: errorColor,
        color: popoverColor,
        textColor: textColor2,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeBorderRadius: borderRadius,
        closeColorHover,
        closeColorPressed,
        headerTextColor: textColor1,
        descriptionTextColor: textColor3,
        actionTextColor: textColor2,
        boxShadow: boxShadow2
      };
    }
    const notificationLight = createTheme({
      name: "Notification",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight
      },
      self: self$K
    });
    const notificationDark = {
      name: "Notification",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark
      },
      self: self$K
    };
    function self$J(vars) {
      const {
        textColor1,
        dividerColor,
        fontWeightStrong
      } = vars;
      return {
        textColor: textColor1,
        color: dividerColor,
        fontWeight: fontWeightStrong
      };
    }
    const dividerLight = {
      name: "Divider",
      common: derived,
      self: self$J
    };
    const dividerDark = {
      name: "Divider",
      common: derived$1,
      self: self$J
    };
    function self$I(vars) {
      const {
        modalColor,
        textColor1,
        textColor2,
        boxShadow3,
        lineHeight: lineHeight2,
        fontWeightStrong,
        dividerColor,
        closeColorHover,
        closeColorPressed,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        borderRadius,
        primaryColorHover
      } = vars;
      return {
        bodyPadding: "16px 24px",
        borderRadius,
        headerPadding: "16px 24px",
        footerPadding: "16px 24px",
        color: modalColor,
        textColor: textColor2,
        titleTextColor: textColor1,
        titleFontSize: "18px",
        titleFontWeight: fontWeightStrong,
        boxShadow: boxShadow3,
        lineHeight: lineHeight2,
        headerBorderBottom: `1px solid ${dividerColor}`,
        footerBorderTop: `1px solid ${dividerColor}`,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeSize: "22px",
        closeIconSize: "18px",
        closeColorHover,
        closeColorPressed,
        closeBorderRadius: borderRadius,
        resizableTriggerColorHover: primaryColorHover
      };
    }
    const drawerLight = createTheme({
      name: "Drawer",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight
      },
      self: self$I
    });
    const drawerDark = {
      name: "Drawer",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark
      },
      self: self$I
    };
    var _common_default$f = {
      actionMargin: "0 0 0 20px",
      actionMarginRtl: "0 20px 0 0"
    };
    const dynamicInputDark = {
      name: "DynamicInput",
      common: derived$1,
      peers: {
        Input: inputDark,
        Button: buttonDark
      },
      self() {
        return _common_default$f;
      }
    };
    function self$H() {
      return _common_default$f;
    }
    const dynamicInputLight = createTheme({
      name: "DynamicInput",
      common: derived,
      peers: {
        Input: inputLight,
        Button: buttonLight
      },
      self: self$H
    });
    var _common_default$e = {
      gapSmall: "4px 8px",
      gapMedium: "8px 12px",
      gapLarge: "12px 16px"
    };
    const spaceDark = {
      name: "Space",
      self() {
        return _common_default$e;
      }
    };
    function self$G() {
      return _common_default$e;
    }
    const spaceLight = {
      name: "Space",
      self: self$G
    };
    const dynamicTagsDark = {
      name: "DynamicTags",
      common: derived$1,
      peers: {
        Input: inputDark,
        Button: buttonDark,
        Tag: tagDark,
        Space: spaceDark
      },
      self() {
        return {
          inputWidth: "64px"
        };
      }
    };
    function self$F() {
      return {
        inputWidth: "64px"
      };
    }
    const dynamicTagsLight = createTheme({
      name: "DynamicTags",
      common: derived,
      peers: {
        Input: inputLight,
        Button: buttonLight,
        Tag: tagLight,
        Space: spaceLight
      },
      self: self$F
    });
    const elementDark = {
      name: "Element",
      common: derived$1
    };
    const elementLight = {
      name: "Element",
      common: derived
    };
    var _common_default$d = {
      gapSmall: "4px 8px",
      gapMedium: "8px 12px",
      gapLarge: "12px 16px"
    };
    const flexDark = {
      name: "Flex",
      self() {
        return _common_default$d;
      }
    };
    function self$E() {
      return _common_default$d;
    }
    const flexLight = {
      name: "Flex",
      self: self$E
    };
    const buttonGroupDark = {
      name: "ButtonGroup",
      common: derived$1
    };
    var _common_default$c = {
      feedbackPadding: "4px 0 0 2px",
      feedbackHeightSmall: "24px",
      feedbackHeightMedium: "24px",
      feedbackHeightLarge: "26px",
      feedbackFontSizeSmall: "13px",
      feedbackFontSizeMedium: "14px",
      feedbackFontSizeLarge: "14px",
      labelFontSizeLeftSmall: "14px",
      labelFontSizeLeftMedium: "14px",
      labelFontSizeLeftLarge: "15px",
      labelFontSizeTopSmall: "13px",
      labelFontSizeTopMedium: "14px",
      labelFontSizeTopLarge: "14px",
      labelHeightSmall: "24px",
      labelHeightMedium: "26px",
      labelHeightLarge: "28px",
      labelPaddingVertical: "0 0 6px 2px",
      labelPaddingHorizontal: "0 12px 0 0",
      labelTextAlignVertical: "left",
      labelTextAlignHorizontal: "right",
      labelFontWeight: "400"
    };
    function self$D(vars) {
      const {
        heightSmall,
        heightMedium,
        heightLarge,
        textColor1,
        errorColor,
        warningColor,
        lineHeight: lineHeight2,
        textColor3
      } = vars;
      return {
        ..._common_default$c,
        blankHeightSmall: heightSmall,
        blankHeightMedium: heightMedium,
        blankHeightLarge: heightLarge,
        lineHeight: lineHeight2,
        labelTextColor: textColor1,
        asteriskColor: errorColor,
        feedbackTextColorError: errorColor,
        feedbackTextColorWarning: warningColor,
        feedbackTextColor: textColor3
      };
    }
    const formLight = {
      name: "Form",
      common: derived,
      self: self$D
    };
    const formItemDark = {
      name: "Form",
      common: derived$1,
      self: self$D
    };
    const gradientTextDark = {
      name: "GradientText",
      common: derived$1,
      self(vars) {
        const {
          primaryColor,
          successColor,
          warningColor,
          errorColor,
          infoColor,
          primaryColorSuppl,
          successColorSuppl,
          warningColorSuppl,
          errorColorSuppl,
          infoColorSuppl,
          fontWeightStrong
        } = vars;
        return {
          fontWeight: fontWeightStrong,
          rotate: "252deg",
          colorStartPrimary: primaryColor,
          colorEndPrimary: primaryColorSuppl,
          colorStartInfo: infoColor,
          colorEndInfo: infoColorSuppl,
          colorStartWarning: warningColor,
          colorEndWarning: warningColorSuppl,
          colorStartError: errorColor,
          colorEndError: errorColorSuppl,
          colorStartSuccess: successColor,
          colorEndSuccess: successColorSuppl
        };
      }
    };
    const inputNumberDark = {
      name: "InputNumber",
      common: derived$1,
      peers: {
        Button: buttonDark,
        Input: inputDark
      },
      self(vars) {
        const {
          textColorDisabled
        } = vars;
        return {
          iconColorDisabled: textColorDisabled
        };
      }
    };
    function self$C() {
      return {
        inputWidthSmall: "24px",
        inputWidthMedium: "30px",
        inputWidthLarge: "36px",
        gapSmall: "8px",
        gapMedium: "8px",
        gapLarge: "8px"
      };
    }
    const inputOtpLight = createTheme({
      name: "InputOtp",
      common: derived,
      peers: {
        Input: inputLight
      },
      self: self$C
    });
    const inputOtpDark = {
      name: "InputOtp",
      common: derived$1,
      peers: {
        Input: inputDark
      },
      self: self$C
    };
    const layoutDark = {
      name: "Layout",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark
      },
      self(vars) {
        const {
          textColor2,
          bodyColor,
          popoverColor,
          cardColor,
          dividerColor,
          scrollbarColor,
          scrollbarColorHover
        } = vars;
        return {
          textColor: textColor2,
          textColorInverted: textColor2,
          color: bodyColor,
          colorEmbedded: bodyColor,
          headerColor: cardColor,
          headerColorInverted: cardColor,
          footerColor: cardColor,
          footerColorInverted: cardColor,
          headerBorderColor: dividerColor,
          headerBorderColorInverted: dividerColor,
          footerBorderColor: dividerColor,
          footerBorderColorInverted: dividerColor,
          siderBorderColor: dividerColor,
          siderBorderColorInverted: dividerColor,
          siderColor: cardColor,
          siderColorInverted: cardColor,
          siderToggleButtonBorder: "1px solid transparent",
          siderToggleButtonColor: popoverColor,
          siderToggleButtonIconColor: textColor2,
          siderToggleButtonIconColorInverted: textColor2,
          siderToggleBarColor: composite(bodyColor, scrollbarColor),
          siderToggleBarColorHover: composite(bodyColor, scrollbarColorHover),
          __invertScrollbar: "false"
        };
      }
    };
    function self$B(vars) {
      const {
        textColor2,
        cardColor,
        modalColor,
        popoverColor,
        dividerColor,
        borderRadius,
        fontSize: fontSize2,
        hoverColor
      } = vars;
      return {
        textColor: textColor2,
        color: cardColor,
        colorHover: hoverColor,
        colorModal: modalColor,
        colorHoverModal: composite(modalColor, hoverColor),
        colorPopover: popoverColor,
        colorHoverPopover: composite(popoverColor, hoverColor),
        borderColor: dividerColor,
        borderColorModal: composite(modalColor, dividerColor),
        borderColorPopover: composite(popoverColor, dividerColor),
        borderRadius,
        fontSize: fontSize2
      };
    }
    const listLight = {
      name: "List",
      common: derived,
      self: self$B
    };
    const listDark$1 = {
      name: "List",
      common: derived$1,
      self: self$B
    };
    const logDark = {
      name: "Log",
      common: derived$1,
      peers: {
        Scrollbar: scrollbarDark,
        Code: codeDark
      },
      self(vars) {
        const {
          textColor2,
          inputColor,
          fontSize: fontSize2,
          primaryColor
        } = vars;
        return {
          loaderFontSize: fontSize2,
          loaderTextColor: textColor2,
          loaderColor: inputColor,
          loaderBorder: "1px solid #0000",
          loadingColor: primaryColor
        };
      }
    };
    const listDark = {
      name: "Mention",
      common: derived$1,
      peers: {
        InternalSelectMenu: internalSelectMenuDark,
        Input: inputDark
      },
      self(vars) {
        const {
          boxShadow2
        } = vars;
        return {
          menuBoxShadow: boxShadow2
        };
      }
    };
    function createPartialInvertedVars(color, activeItemColor, activeTextColor, groupTextColor) {
      return {
        itemColorHoverInverted: "#0000",
        itemColorActiveInverted: activeItemColor,
        itemColorActiveHoverInverted: activeItemColor,
        itemColorActiveCollapsedInverted: activeItemColor,
        itemTextColorInverted: color,
        itemTextColorHoverInverted: activeTextColor,
        itemTextColorChildActiveInverted: activeTextColor,
        itemTextColorChildActiveHoverInverted: activeTextColor,
        itemTextColorActiveInverted: activeTextColor,
        itemTextColorActiveHoverInverted: activeTextColor,
        itemTextColorHorizontalInverted: color,
        itemTextColorHoverHorizontalInverted: activeTextColor,
        itemTextColorChildActiveHorizontalInverted: activeTextColor,
        itemTextColorChildActiveHoverHorizontalInverted: activeTextColor,
        itemTextColorActiveHorizontalInverted: activeTextColor,
        itemTextColorActiveHoverHorizontalInverted: activeTextColor,
        itemIconColorInverted: color,
        itemIconColorHoverInverted: activeTextColor,
        itemIconColorActiveInverted: activeTextColor,
        itemIconColorActiveHoverInverted: activeTextColor,
        itemIconColorChildActiveInverted: activeTextColor,
        itemIconColorChildActiveHoverInverted: activeTextColor,
        itemIconColorCollapsedInverted: color,
        itemIconColorHorizontalInverted: color,
        itemIconColorHoverHorizontalInverted: activeTextColor,
        itemIconColorActiveHorizontalInverted: activeTextColor,
        itemIconColorActiveHoverHorizontalInverted: activeTextColor,
        itemIconColorChildActiveHorizontalInverted: activeTextColor,
        itemIconColorChildActiveHoverHorizontalInverted: activeTextColor,
        arrowColorInverted: color,
        arrowColorHoverInverted: activeTextColor,
        arrowColorActiveInverted: activeTextColor,
        arrowColorActiveHoverInverted: activeTextColor,
        arrowColorChildActiveInverted: activeTextColor,
        arrowColorChildActiveHoverInverted: activeTextColor,
        groupTextColorInverted: groupTextColor
      };
    }
    function self$A(vars) {
      const {
        borderRadius,
        textColor3,
        primaryColor,
        textColor2,
        textColor1,
        fontSize: fontSize2,
        dividerColor,
        hoverColor,
        primaryColorHover
      } = vars;
      return {
        borderRadius,
        color: "#0000",
        groupTextColor: textColor3,
        itemColorHover: hoverColor,
        itemColorActive: changeColor(primaryColor, {
          alpha: 0.1
        }),
        itemColorActiveHover: changeColor(primaryColor, {
          alpha: 0.1
        }),
        itemColorActiveCollapsed: changeColor(primaryColor, {
          alpha: 0.1
        }),
        itemTextColor: textColor2,
        itemTextColorHover: textColor2,
        itemTextColorActive: primaryColor,
        itemTextColorActiveHover: primaryColor,
        itemTextColorChildActive: primaryColor,
        itemTextColorChildActiveHover: primaryColor,
        itemTextColorHorizontal: textColor2,
        itemTextColorHoverHorizontal: primaryColorHover,
        itemTextColorActiveHorizontal: primaryColor,
        itemTextColorActiveHoverHorizontal: primaryColor,
        itemTextColorChildActiveHorizontal: primaryColor,
        itemTextColorChildActiveHoverHorizontal: primaryColor,
        itemIconColor: textColor1,
        itemIconColorHover: textColor1,
        itemIconColorActive: primaryColor,
        itemIconColorActiveHover: primaryColor,
        itemIconColorChildActive: primaryColor,
        itemIconColorChildActiveHover: primaryColor,
        itemIconColorCollapsed: textColor1,
        itemIconColorHorizontal: textColor1,
        itemIconColorHoverHorizontal: primaryColorHover,
        itemIconColorActiveHorizontal: primaryColor,
        itemIconColorActiveHoverHorizontal: primaryColor,
        itemIconColorChildActiveHorizontal: primaryColor,
        itemIconColorChildActiveHoverHorizontal: primaryColor,
        itemHeight: "42px",
        arrowColor: textColor2,
        arrowColorHover: textColor2,
        arrowColorActive: primaryColor,
        arrowColorActiveHover: primaryColor,
        arrowColorChildActive: primaryColor,
        arrowColorChildActiveHover: primaryColor,
        colorInverted: "#0000",
        borderColorHorizontal: "#0000",
        fontSize: fontSize2,
        dividerColor,
        ...createPartialInvertedVars("#BBB", primaryColor, "#FFF", "#AAA")
      };
    }
    const menuLight = createTheme({
      name: "Menu",
      common: derived,
      peers: {
        Tooltip: tooltipLight,
        Dropdown: dropdownLight
      },
      self: self$A
    });
    const menuDark = {
      name: "Menu",
      common: derived$1,
      peers: {
        Tooltip: tooltipDark,
        Dropdown: dropdownDark
      },
      self(vars) {
        const {
          primaryColor,
          primaryColorSuppl
        } = vars;
        const commonSelf = self$A(vars);
        commonSelf.itemColorActive = changeColor(primaryColor, {
          alpha: 0.15
        });
        commonSelf.itemColorActiveHover = changeColor(primaryColor, {
          alpha: 0.15
        });
        commonSelf.itemColorActiveCollapsed = changeColor(primaryColor, {
          alpha: 0.15
        });
        commonSelf.itemColorActiveInverted = primaryColorSuppl;
        commonSelf.itemColorActiveHoverInverted = primaryColorSuppl;
        commonSelf.itemColorActiveCollapsedInverted = primaryColorSuppl;
        return commonSelf;
      }
    };
    var _common_default$b = {
      iconSize: "22px"
    };
    function self$z(vars) {
      const {
        fontSize: fontSize2,
        warningColor
      } = vars;
      return {
        ..._common_default$b,
        fontSize: fontSize2,
        iconColor: warningColor
      };
    }
    const popconfirmLight = createTheme({
      name: "Popconfirm",
      common: derived,
      peers: {
        Button: buttonLight,
        Popover: popoverLight
      },
      self: self$z
    });
    const popconfirmDark = {
      name: "Popconfirm",
      common: derived$1,
      peers: {
        Button: buttonDark,
        Popover: popoverDark
      },
      self: self$z
    };
    function self$y(vars) {
      const {
        infoColor,
        successColor,
        warningColor,
        errorColor,
        textColor2,
        progressRailColor,
        fontSize: fontSize2,
        fontWeight
      } = vars;
      return {
        fontSize: fontSize2,
        fontSizeCircle: "28px",
        fontWeightCircle: fontWeight,
        railColor: progressRailColor,
        railHeight: "8px",
        iconSizeCircle: "36px",
        iconSizeLine: "18px",
        iconColor: infoColor,
        iconColorInfo: infoColor,
        iconColorSuccess: successColor,
        iconColorWarning: warningColor,
        iconColorError: errorColor,
        textColorCircle: textColor2,
        textColorLineInner: "rgb(255, 255, 255)",
        textColorLineOuter: textColor2,
        fillColor: infoColor,
        fillColorInfo: infoColor,
        fillColorSuccess: successColor,
        fillColorWarning: warningColor,
        fillColorError: errorColor,
        lineBgProcessing: "linear-gradient(90deg, rgba(255, 255, 255, .3) 0%, rgba(255, 255, 255, .5) 100%)"
      };
    }
    const progressLight = {
      name: "Progress",
      common: derived,
      self: self$y
    };
    const progressDark = {
      name: "Progress",
      common: derived$1,
      self(vars) {
        const commonSelf = self$y(vars);
        commonSelf.textColorLineInner = "rgb(0, 0, 0)";
        commonSelf.lineBgProcessing = "linear-gradient(90deg, rgba(255, 255, 255, .3) 0%, rgba(255, 255, 255, .5) 100%)";
        return commonSelf;
      }
    };
    const rateDark = {
      name: "Rate",
      common: derived$1,
      self(vars) {
        const {
          railColor
        } = vars;
        return {
          itemColor: railColor,
          itemColorActive: "#CCAA33",
          itemSize: "20px",
          sizeSmall: "16px",
          sizeMedium: "20px",
          sizeLarge: "24px"
        };
      }
    };
    var _common_default$a = {
      titleFontSizeSmall: "26px",
      titleFontSizeMedium: "32px",
      titleFontSizeLarge: "40px",
      titleFontSizeHuge: "48px",
      fontSizeSmall: "14px",
      fontSizeMedium: "14px",
      fontSizeLarge: "15px",
      fontSizeHuge: "16px",
      iconSizeSmall: "64px",
      iconSizeMedium: "80px",
      iconSizeLarge: "100px",
      iconSizeHuge: "125px",
      iconColor418: void 0,
      iconColor404: void 0,
      iconColor403: void 0,
      iconColor500: void 0
    };
    function self$x(vars) {
      const {
        textColor2,
        textColor1,
        errorColor,
        successColor,
        infoColor,
        warningColor,
        lineHeight: lineHeight2,
        fontWeightStrong
      } = vars;
      return {
        ..._common_default$a,
        lineHeight: lineHeight2,
        titleFontWeight: fontWeightStrong,
        titleTextColor: textColor1,
        textColor: textColor2,
        iconColorError: errorColor,
        iconColorSuccess: successColor,
        iconColorInfo: infoColor,
        iconColorWarning: warningColor
      };
    }
    const resultLight = {
      name: "Result",
      common: derived,
      self: self$x
    };
    const resultDark = {
      name: "Result",
      common: derived$1,
      self: self$x
    };
    var _common_default$9 = {
      railHeight: "4px",
      railWidthVertical: "4px",
      handleSize: "18px",
      dotHeight: "8px",
      dotWidth: "8px",
      dotBorderRadius: "4px"
    };
    const sliderDark = {
      name: "Slider",
      common: derived$1,
      self(vars) {
        const boxShadow = "0 2px 8px 0 rgba(0, 0, 0, 0.12)";
        const {
          railColor,
          modalColor,
          primaryColorSuppl,
          popoverColor,
          textColor2,
          cardColor,
          borderRadius,
          fontSize: fontSize2,
          opacityDisabled
        } = vars;
        return {
          ..._common_default$9,
          fontSize: fontSize2,
          markFontSize: fontSize2,
          railColor,
          railColorHover: railColor,
          fillColor: primaryColorSuppl,
          fillColorHover: primaryColorSuppl,
          opacityDisabled,
          handleColor: "#FFF",
          dotColor: cardColor,
          dotColorModal: modalColor,
          dotColorPopover: popoverColor,
          handleBoxShadow: "0px 2px 4px 0 rgba(0, 0, 0, 0.4)",
          handleBoxShadowHover: "0px 2px 4px 0 rgba(0, 0, 0, 0.4)",
          handleBoxShadowActive: "0px 2px 4px 0 rgba(0, 0, 0, 0.4)",
          handleBoxShadowFocus: "0px 2px 4px 0 rgba(0, 0, 0, 0.4)",
          indicatorColor: popoverColor,
          indicatorBoxShadow: boxShadow,
          indicatorTextColor: textColor2,
          indicatorBorderRadius: borderRadius,
          dotBorder: `2px solid ${railColor}`,
          dotBorderActive: `2px solid ${primaryColorSuppl}`,
          dotBoxShadow: ""
        };
      }
    };
    function self$w(vars) {
      const {
        opacityDisabled,
        heightTiny,
        heightSmall,
        heightMedium,
        heightLarge,
        heightHuge,
        primaryColor,
        fontSize: fontSize2
      } = vars;
      return {
        fontSize: fontSize2,
        textColor: primaryColor,
        sizeTiny: heightTiny,
        sizeSmall: heightSmall,
        sizeMedium: heightMedium,
        sizeLarge: heightLarge,
        sizeHuge: heightHuge,
        color: primaryColor,
        opacitySpinning: opacityDisabled
      };
    }
    const spinLight = {
      name: "Spin",
      common: derived,
      self: self$w
    };
    const spinDark = {
      name: "Spin",
      common: derived$1,
      self: self$w
    };
    function self$v(vars) {
      const {
        textColor2,
        textColor3,
        fontSize: fontSize2,
        fontWeight
      } = vars;
      return {
        labelFontSize: fontSize2,
        labelFontWeight: fontWeight,
        valueFontWeight: fontWeight,
        valueFontSize: "24px",
        labelTextColor: textColor3,
        valuePrefixTextColor: textColor2,
        valueSuffixTextColor: textColor2,
        valueTextColor: textColor2
      };
    }
    const statisticLight = {
      name: "Statistic",
      common: derived,
      self: self$v
    };
    const statisticDark = {
      name: "Statistic",
      common: derived$1,
      self: self$v
    };
    var _common_default$8 = {
      stepHeaderFontSizeSmall: "14px",
      stepHeaderFontSizeMedium: "16px",
      indicatorIndexFontSizeSmall: "14px",
      indicatorIndexFontSizeMedium: "16px",
      indicatorSizeSmall: "22px",
      indicatorSizeMedium: "28px",
      indicatorIconSizeSmall: "14px",
      indicatorIconSizeMedium: "18px"
    };
    function self$u(vars) {
      const {
        fontWeightStrong,
        baseColor,
        textColorDisabled,
        primaryColor,
        errorColor,
        textColor1,
        textColor2
      } = vars;
      return {
        ..._common_default$8,
        stepHeaderFontWeight: fontWeightStrong,
        indicatorTextColorProcess: baseColor,
        indicatorTextColorWait: textColorDisabled,
        indicatorTextColorFinish: primaryColor,
        indicatorTextColorError: errorColor,
        indicatorBorderColorProcess: primaryColor,
        indicatorBorderColorWait: textColorDisabled,
        indicatorBorderColorFinish: primaryColor,
        indicatorBorderColorError: errorColor,
        indicatorColorProcess: primaryColor,
        indicatorColorWait: "#0000",
        indicatorColorFinish: "#0000",
        indicatorColorError: "#0000",
        splitorColorProcess: textColorDisabled,
        splitorColorWait: textColorDisabled,
        splitorColorFinish: primaryColor,
        splitorColorError: textColorDisabled,
        headerTextColorProcess: textColor1,
        headerTextColorWait: textColorDisabled,
        headerTextColorFinish: textColorDisabled,
        headerTextColorError: errorColor,
        descriptionTextColorProcess: textColor2,
        descriptionTextColorWait: textColorDisabled,
        descriptionTextColorFinish: textColorDisabled,
        descriptionTextColorError: errorColor
      };
    }
    const stepsLight = {
      name: "Steps",
      common: derived,
      self: self$u
    };
    const stepsDark = {
      name: "Steps",
      common: derived$1,
      self: self$u
    };
    var _common_default$7 = {
      buttonHeightSmall: "14px",
      buttonHeightMedium: "18px",
      buttonHeightLarge: "22px",
      buttonWidthSmall: "14px",
      buttonWidthMedium: "18px",
      buttonWidthLarge: "22px",
      buttonWidthPressedSmall: "20px",
      buttonWidthPressedMedium: "24px",
      buttonWidthPressedLarge: "28px",
      railHeightSmall: "18px",
      railHeightMedium: "22px",
      railHeightLarge: "26px",
      railWidthSmall: "32px",
      railWidthMedium: "40px",
      railWidthLarge: "48px"
    };
    const switchDark = {
      name: "Switch",
      common: derived$1,
      self(vars) {
        const {
          primaryColorSuppl,
          opacityDisabled,
          borderRadius,
          primaryColor,
          textColor2,
          baseColor
        } = vars;
        const railOverlayColor = "rgba(255, 255, 255, .20)";
        return {
          ..._common_default$7,
          iconColor: baseColor,
          textColor: textColor2,
          loadingColor: primaryColorSuppl,
          opacityDisabled,
          railColor: railOverlayColor,
          railColorActive: primaryColorSuppl,
          buttonBoxShadow: "0px 2px 4px 0 rgba(0, 0, 0, 0.4)",
          buttonColor: "#FFF",
          railBorderRadiusSmall: borderRadius,
          railBorderRadiusMedium: borderRadius,
          railBorderRadiusLarge: borderRadius,
          buttonBorderRadiusSmall: borderRadius,
          buttonBorderRadiusMedium: borderRadius,
          buttonBorderRadiusLarge: borderRadius,
          boxShadowFocus: `0 0 8px 0 ${changeColor(primaryColor, {
            alpha: 0.3
          })}`
        };
      }
    };
    var _common_default$6 = {
      thPaddingSmall: "6px",
      thPaddingMedium: "12px",
      thPaddingLarge: "12px",
      tdPaddingSmall: "6px",
      tdPaddingMedium: "12px",
      tdPaddingLarge: "12px"
    };
    function self$t(vars) {
      const {
        dividerColor,
        cardColor,
        modalColor,
        popoverColor,
        tableHeaderColor,
        tableColorStriped,
        textColor1,
        textColor2,
        borderRadius,
        fontWeightStrong,
        lineHeight: lineHeight2,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge
      } = vars;
      return {
        ..._common_default$6,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        lineHeight: lineHeight2,
        borderRadius,
        borderColor: composite(cardColor, dividerColor),
        borderColorModal: composite(modalColor, dividerColor),
        borderColorPopover: composite(popoverColor, dividerColor),
        tdColor: cardColor,
        tdColorModal: modalColor,
        tdColorPopover: popoverColor,
        tdColorStriped: composite(cardColor, tableColorStriped),
        tdColorStripedModal: composite(modalColor, tableColorStriped),
        tdColorStripedPopover: composite(popoverColor, tableColorStriped),
        thColor: composite(cardColor, tableHeaderColor),
        thColorModal: composite(modalColor, tableHeaderColor),
        thColorPopover: composite(popoverColor, tableHeaderColor),
        thTextColor: textColor1,
        tdTextColor: textColor2,
        thFontWeight: fontWeightStrong
      };
    }
    const tableLight = {
      name: "Table",
      common: derived,
      self: self$t
    };
    const tableDark = {
      name: "Table",
      common: derived$1,
      self: self$t
    };
    var _common_default$5 = {
      tabFontSizeSmall: "14px",
      tabFontSizeMedium: "14px",
      tabFontSizeLarge: "16px",
      tabGapSmallLine: "36px",
      tabGapMediumLine: "36px",
      tabGapLargeLine: "36px",
      tabGapSmallLineVertical: "8px",
      tabGapMediumLineVertical: "8px",
      tabGapLargeLineVertical: "8px",
      tabPaddingSmallLine: "6px 0",
      tabPaddingMediumLine: "10px 0",
      tabPaddingLargeLine: "14px 0",
      tabPaddingVerticalSmallLine: "6px 12px",
      tabPaddingVerticalMediumLine: "8px 16px",
      tabPaddingVerticalLargeLine: "10px 20px",
      tabGapSmallBar: "36px",
      tabGapMediumBar: "36px",
      tabGapLargeBar: "36px",
      tabGapSmallBarVertical: "8px",
      tabGapMediumBarVertical: "8px",
      tabGapLargeBarVertical: "8px",
      tabPaddingSmallBar: "4px 0",
      tabPaddingMediumBar: "6px 0",
      tabPaddingLargeBar: "10px 0",
      tabPaddingVerticalSmallBar: "6px 12px",
      tabPaddingVerticalMediumBar: "8px 16px",
      tabPaddingVerticalLargeBar: "10px 20px",
      tabGapSmallCard: "4px",
      tabGapMediumCard: "4px",
      tabGapLargeCard: "4px",
      tabGapSmallCardVertical: "4px",
      tabGapMediumCardVertical: "4px",
      tabGapLargeCardVertical: "4px",
      tabPaddingSmallCard: "8px 16px",
      tabPaddingMediumCard: "10px 20px",
      tabPaddingLargeCard: "12px 24px",
      tabPaddingSmallSegment: "4px 0",
      tabPaddingMediumSegment: "6px 0",
      tabPaddingLargeSegment: "8px 0",
      tabPaddingVerticalLargeSegment: "0 8px",
      tabPaddingVerticalSmallCard: "8px 12px",
      tabPaddingVerticalMediumCard: "10px 16px",
      tabPaddingVerticalLargeCard: "12px 20px",
      tabPaddingVerticalSmallSegment: "0 4px",
      tabPaddingVerticalMediumSegment: "0 6px",
      tabGapSmallSegment: "0",
      tabGapMediumSegment: "0",
      tabGapLargeSegment: "0",
      tabGapSmallSegmentVertical: "0",
      tabGapMediumSegmentVertical: "0",
      tabGapLargeSegmentVertical: "0",
      panePaddingSmall: "8px 0 0 0",
      panePaddingMedium: "12px 0 0 0",
      panePaddingLarge: "16px 0 0 0",
      closeSize: "18px",
      closeIconSize: "14px"
    };
    function self$s(vars) {
      const {
        textColor2,
        primaryColor,
        textColorDisabled,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeColorHover,
        closeColorPressed,
        tabColor,
        baseColor,
        dividerColor,
        fontWeight,
        textColor1,
        borderRadius,
        fontSize: fontSize2,
        fontWeightStrong
      } = vars;
      return {
        ..._common_default$5,
        colorSegment: tabColor,
        tabFontSizeCard: fontSize2,
        tabTextColorLine: textColor1,
        tabTextColorActiveLine: primaryColor,
        tabTextColorHoverLine: primaryColor,
        tabTextColorDisabledLine: textColorDisabled,
        tabTextColorSegment: textColor1,
        tabTextColorActiveSegment: textColor2,
        tabTextColorHoverSegment: textColor2,
        tabTextColorDisabledSegment: textColorDisabled,
        tabTextColorBar: textColor1,
        tabTextColorActiveBar: primaryColor,
        tabTextColorHoverBar: primaryColor,
        tabTextColorDisabledBar: textColorDisabled,
        tabTextColorCard: textColor1,
        tabTextColorHoverCard: textColor1,
        tabTextColorActiveCard: primaryColor,
        tabTextColorDisabledCard: textColorDisabled,
        barColor: primaryColor,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed,
        closeColorHover,
        closeColorPressed,
        closeBorderRadius: borderRadius,
        tabColor,
        tabColorSegment: baseColor,
        tabBorderColor: dividerColor,
        tabFontWeightActive: fontWeight,
        tabFontWeight: fontWeight,
        tabBorderRadius: borderRadius,
        paneTextColor: textColor2,
        fontWeightStrong
      };
    }
    const tabsLight = createTheme({
      name: "Tabs",
      common: derived,
      peers: {
        Button: buttonLight
      },
      self: self$s
    });
    const tabsDark = {
      name: "Tabs",
      common: derived$1,
      peers: {
        Button: buttonDark
      },
      self(vars) {
        const commonSelf = self$s(vars);
        const {
          inputColor
        } = vars;
        commonSelf.colorSegment = inputColor;
        commonSelf.tabColorSegment = inputColor;
        return commonSelf;
      }
    };
    function self$r(vars) {
      const {
        textColor1,
        textColor2,
        fontWeightStrong,
        fontSize: fontSize2
      } = vars;
      return {
        fontSize: fontSize2,
        titleTextColor: textColor1,
        textColor: textColor2,
        titleFontWeight: fontWeightStrong
      };
    }
    const thingLight = {
      name: "Thing",
      common: derived,
      self: self$r
    };
    const thingDark = {
      name: "Thing",
      common: derived$1,
      self: self$r
    };
    var _common_default$4 = {
      titleMarginMedium: "0 0 6px 0",
      titleMarginLarge: "-2px 0 6px 0",
      titleFontSizeMedium: "14px",
      titleFontSizeLarge: "16px",
      iconSizeMedium: "14px",
      iconSizeLarge: "14px"
    };
    const timelineDark = {
      name: "Timeline",
      common: derived$1,
      self(vars) {
        const {
          textColor3,
          infoColorSuppl,
          errorColorSuppl,
          successColorSuppl,
          warningColorSuppl,
          textColor1,
          textColor2,
          railColor,
          fontWeightStrong,
          fontSize: fontSize2
        } = vars;
        return {
          ..._common_default$4,
          contentFontSize: fontSize2,
          titleFontWeight: fontWeightStrong,
          circleBorder: `2px solid ${textColor3}`,
          circleBorderInfo: `2px solid ${infoColorSuppl}`,
          circleBorderError: `2px solid ${errorColorSuppl}`,
          circleBorderSuccess: `2px solid ${successColorSuppl}`,
          circleBorderWarning: `2px solid ${warningColorSuppl}`,
          iconColor: textColor3,
          iconColorInfo: infoColorSuppl,
          iconColorError: errorColorSuppl,
          iconColorSuccess: successColorSuppl,
          iconColorWarning: warningColorSuppl,
          titleTextColor: textColor1,
          contentTextColor: textColor2,
          metaTextColor: textColor3,
          lineColor: railColor
        };
      }
    };
    var _common_default$3 = {
      extraFontSizeSmall: "12px",
      extraFontSizeMedium: "12px",
      extraFontSizeLarge: "14px",
      titleFontSizeSmall: "14px",
      titleFontSizeMedium: "16px",
      titleFontSizeLarge: "16px",
      closeSize: "20px",
      closeIconSize: "16px",
      headerHeightSmall: "44px",
      headerHeightMedium: "44px",
      headerHeightLarge: "50px"
    };
    const transferDark$1 = {
      name: "Transfer",
      common: derived$1,
      peers: {
        Checkbox: checkboxDark,
        Scrollbar: scrollbarDark,
        Input: inputDark,
        Empty: emptyDark,
        Button: buttonDark
      },
      self(vars) {
        const {
          fontWeight,
          fontSizeLarge,
          fontSizeMedium,
          fontSizeSmall,
          heightLarge,
          heightMedium,
          borderRadius,
          inputColor,
          tableHeaderColor,
          textColor1,
          textColorDisabled,
          textColor2,
          textColor3,
          hoverColor,
          closeColorHover,
          closeColorPressed,
          closeIconColor,
          closeIconColorHover,
          closeIconColorPressed,
          dividerColor
        } = vars;
        return {
          ..._common_default$3,
          itemHeightSmall: heightMedium,
          itemHeightMedium: heightMedium,
          itemHeightLarge: heightLarge,
          fontSizeSmall,
          fontSizeMedium,
          fontSizeLarge,
          borderRadius,
          dividerColor,
          borderColor: "#0000",
          listColor: inputColor,
          headerColor: tableHeaderColor,
          titleTextColor: textColor1,
          titleTextColorDisabled: textColorDisabled,
          extraTextColor: textColor3,
          extraTextColorDisabled: textColorDisabled,
          itemTextColor: textColor2,
          itemTextColorDisabled: textColorDisabled,
          itemColorPending: hoverColor,
          titleFontWeight: fontWeight,
          closeColorHover,
          closeColorPressed,
          closeIconColor,
          closeIconColorHover,
          closeIconColorPressed
        };
      }
    };
    function self$q(vars) {
      const {
        borderRadiusSmall,
        dividerColor,
        hoverColor,
        pressedColor,
        primaryColor,
        textColor3,
        textColor2,
        textColorDisabled,
        fontSize: fontSize2
      } = vars;
      return {
        fontSize: fontSize2,
        lineHeight: "1.5",
        nodeHeight: "30px",
        nodeWrapperPadding: "3px 0",
        nodeBorderRadius: borderRadiusSmall,
        nodeColorHover: hoverColor,
        nodeColorPressed: pressedColor,
        nodeColorActive: changeColor(primaryColor, {
          alpha: 0.1
        }),
        arrowColor: textColor3,
        nodeTextColor: textColor2,
        nodeTextColorDisabled: textColorDisabled,
        loadingColor: primaryColor,
        dropMarkColor: primaryColor,
        lineColor: dividerColor
      };
    }
    const treeLight = createTheme({
      name: "Tree",
      common: derived,
      peers: {
        Checkbox: checkboxLight,
        Scrollbar: scrollbarLight,
        Empty: emptyLight
      },
      self: self$q
    });
    const treeDark = {
      name: "Tree",
      common: derived$1,
      peers: {
        Checkbox: checkboxDark,
        Scrollbar: scrollbarDark,
        Empty: emptyDark
      },
      self(vars) {
        const {
          primaryColor
        } = vars;
        const commonSelf = self$q(vars);
        commonSelf.nodeColorActive = changeColor(primaryColor, {
          alpha: 0.15
        });
        return commonSelf;
      }
    };
    const treeSelectDark = {
      name: "TreeSelect",
      common: derived$1,
      peers: {
        Tree: treeDark,
        Empty: emptyDark,
        InternalSelection: internalSelectionDark
      }
    };
    var _common_default$2 = {
      headerFontSize1: "30px",
      headerFontSize2: "22px",
      headerFontSize3: "18px",
      headerFontSize4: "16px",
      headerFontSize5: "16px",
      headerFontSize6: "16px",
      headerMargin1: "28px 0 20px 0",
      headerMargin2: "28px 0 20px 0",
      headerMargin3: "28px 0 20px 0",
      headerMargin4: "28px 0 18px 0",
      headerMargin5: "28px 0 18px 0",
      headerMargin6: "28px 0 18px 0",
      headerPrefixWidth1: "16px",
      headerPrefixWidth2: "16px",
      headerPrefixWidth3: "12px",
      headerPrefixWidth4: "12px",
      headerPrefixWidth5: "12px",
      headerPrefixWidth6: "12px",
      headerBarWidth1: "4px",
      headerBarWidth2: "4px",
      headerBarWidth3: "3px",
      headerBarWidth4: "3px",
      headerBarWidth5: "3px",
      headerBarWidth6: "3px",
      pMargin: "16px 0 16px 0",
      liMargin: ".25em 0 0 0",
      olPadding: "0 0 0 2em",
      ulPadding: "0 0 0 2em"
    };
    function self$p(vars) {
      const {
        primaryColor,
        textColor2,
        borderColor,
        lineHeight: lineHeight2,
        fontSize: fontSize2,
        borderRadiusSmall,
        dividerColor,
        fontWeightStrong,
        textColor1,
        textColor3,
        infoColor,
        warningColor,
        errorColor,
        successColor,
        codeColor
      } = vars;
      return {
        ..._common_default$2,
        aTextColor: primaryColor,
        blockquoteTextColor: textColor2,
        blockquotePrefixColor: borderColor,
        blockquoteLineHeight: lineHeight2,
        blockquoteFontSize: fontSize2,
        codeBorderRadius: borderRadiusSmall,
        liTextColor: textColor2,
        liLineHeight: lineHeight2,
        liFontSize: fontSize2,
        hrColor: dividerColor,
        headerFontWeight: fontWeightStrong,
        headerTextColor: textColor1,
        pTextColor: textColor2,
        pTextColor1Depth: textColor1,
        pTextColor2Depth: textColor2,
        pTextColor3Depth: textColor3,
        pLineHeight: lineHeight2,
        pFontSize: fontSize2,
        headerBarColor: primaryColor,
        headerBarColorPrimary: primaryColor,
        headerBarColorInfo: infoColor,
        headerBarColorError: errorColor,
        headerBarColorWarning: warningColor,
        headerBarColorSuccess: successColor,
        textColor: textColor2,
        textColor1Depth: textColor1,
        textColor2Depth: textColor2,
        textColor3Depth: textColor3,
        textColorPrimary: primaryColor,
        textColorInfo: infoColor,
        textColorSuccess: successColor,
        textColorWarning: warningColor,
        textColorError: errorColor,
        codeTextColor: textColor2,
        codeColor,
        codeBorder: "1px solid #0000"
      };
    }
    const typographyLight = {
      name: "Typography",
      common: derived,
      self: self$p
    };
    const typographyDark = {
      name: "Typography",
      common: derived$1,
      self: self$p
    };
    function self$o(vars) {
      const {
        iconColor,
        primaryColor,
        errorColor,
        textColor2,
        successColor,
        opacityDisabled,
        actionColor,
        borderColor,
        hoverColor,
        lineHeight: lineHeight2,
        borderRadius,
        fontSize: fontSize2
      } = vars;
      return {
        fontSize: fontSize2,
        lineHeight: lineHeight2,
        borderRadius,
        draggerColor: actionColor,
        draggerBorder: `1px dashed ${borderColor}`,
        draggerBorderHover: `1px dashed ${primaryColor}`,
        itemColorHover: hoverColor,
        itemColorHoverError: changeColor(errorColor, {
          alpha: 0.06
        }),
        itemTextColor: textColor2,
        itemTextColorError: errorColor,
        itemTextColorSuccess: successColor,
        itemIconColor: iconColor,
        itemDisabledOpacity: opacityDisabled,
        itemBorderImageCardError: `1px solid ${errorColor}`,
        itemBorderImageCard: `1px solid ${borderColor}`
      };
    }
    const uploadLight = createTheme({
      name: "Upload",
      common: derived,
      peers: {
        Button: buttonLight,
        Progress: progressLight
      },
      self: self$o
    });
    const uploadDark = {
      name: "Upload",
      common: derived$1,
      peers: {
        Button: buttonDark,
        Progress: progressDark
      },
      self(vars) {
        const {
          errorColor
        } = vars;
        const commonSelf = self$o(vars);
        commonSelf.itemColorHoverError = changeColor(errorColor, {
          alpha: 0.09
        });
        return commonSelf;
      }
    };
    const watermarkDark = {
      name: "Watermark",
      common: derived$1,
      self(vars) {
        const {
          fontFamily: fontFamily2
        } = vars;
        return {
          fontFamily: fontFamily2
        };
      }
    };
    function self$n(vars) {
      const {
        popoverColor,
        dividerColor,
        borderRadius
      } = vars;
      return {
        color: popoverColor,
        buttonBorderColor: dividerColor,
        borderRadiusSquare: borderRadius,
        boxShadow: "0 2px 8px 0px rgba(0, 0, 0, .12)"
      };
    }
    const themeLight$4 = {
      name: "FloatButtonGroup",
      common: derived,
      self: self$n
    };
    function self$m(vars) {
      const {
        popoverColor,
        textColor2,
        buttonColor2Hover,
        buttonColor2Pressed,
        primaryColor,
        primaryColorHover,
        primaryColorPressed,
        borderRadius
      } = vars;
      return {
        color: popoverColor,
        colorHover: buttonColor2Hover,
        colorPressed: buttonColor2Pressed,
        colorPrimary: primaryColor,
        colorPrimaryHover: primaryColorHover,
        colorPrimaryPressed: primaryColorPressed,
        textColor: textColor2,
        boxShadow: "0 2px 8px 0px rgba(0, 0, 0, .16)",
        boxShadowHover: "0 2px 12px 0px rgba(0, 0, 0, .24)",
        boxShadowPressed: "0 2px 12px 0px rgba(0, 0, 0, .24)",
        textColorPrimary: "#fff",
        borderRadiusSquare: borderRadius
      };
    }
    const themeLight$3 = {
      name: "FloatButton",
      common: derived,
      self: self$m
    };
    let houdiniRegistered = false;
    function useHoudini() {
      if (!isBrowser) return;
      if (!window.CSS) return;
      if (!houdiniRegistered) {
        houdiniRegistered = true;
        if ("registerProperty" in window?.CSS) try {
          CSS.registerProperty({
            name: "--n-color-start",
            syntax: "<color>",
            inherits: false,
            initialValue: "#0000"
          });
          CSS.registerProperty({
            name: "--n-color-end",
            syntax: "<color>",
            inherits: false,
            initialValue: "#0000"
          });
        } catch {
        }
      }
    }
    function self$l(vars) {
      const {
        primaryColor,
        successColor,
        warningColor,
        errorColor,
        infoColor,
        fontWeightStrong
      } = vars;
      return {
        fontWeight: fontWeightStrong,
        rotate: "252deg",
        colorStartPrimary: changeColor(primaryColor, {
          alpha: 0.6
        }),
        colorEndPrimary: primaryColor,
        colorStartInfo: changeColor(infoColor, {
          alpha: 0.6
        }),
        colorEndInfo: infoColor,
        colorStartWarning: changeColor(warningColor, {
          alpha: 0.6
        }),
        colorEndWarning: warningColor,
        colorStartError: changeColor(errorColor, {
          alpha: 0.6
        }),
        colorEndError: errorColor,
        colorStartSuccess: changeColor(successColor, {
          alpha: 0.6
        }),
        colorEndSuccess: successColor
      };
    }
    const gradientTextLight = {
      name: "GradientText",
      common: derived,
      self: self$l
    };
    function self$k(vars) {
      const {
        borderRadius,
        fontSizeMini,
        fontSizeTiny,
        fontSizeSmall,
        fontWeight,
        textColor2,
        cardColor,
        buttonColor2Hover
      } = vars;
      return {
        activeColors: ["#9be9a8", "#40c463", "#30a14e", "#216e39"],
        borderRadius,
        borderColor: cardColor,
        textColor: textColor2,
        mininumColor: buttonColor2Hover,
        fontWeight,
        loadingColorStart: "rgba(0, 0, 0, 0.06)",
        loadingColorEnd: "rgba(0, 0, 0, 0.12)",
        rectSizeSmall: "10px",
        rectSizeMedium: "11px",
        rectSizeLarge: "12px",
        borderRadiusSmall: "2px",
        borderRadiusMedium: "2px",
        borderRadiusLarge: "2px",
        xGapSmall: "2px",
        xGapMedium: "3px",
        xGapLarge: "3px",
        yGapSmall: "2px",
        yGapMedium: "3px",
        yGapLarge: "3px",
        fontSizeSmall: fontSizeTiny,
        fontSizeMedium: fontSizeMini,
        fontSizeLarge: fontSizeSmall
      };
    }
    const heatmapLight = createTheme({
      name: "Heatmap",
      common: derived,
      self: self$k
    });
    function self$j(vars) {
      const {
        primaryColor,
        baseColor
      } = vars;
      return {
        color: primaryColor,
        iconColor: baseColor
      };
    }
    const iconWrapperLight = {
      name: "IconWrapper",
      common: derived,
      self: self$j
    };
    function self$i() {
      return {
        toolbarIconColor: "rgba(255, 255, 255, .9)",
        toolbarColor: "rgba(0, 0, 0, .35)",
        toolbarBoxShadow: "none",
        toolbarBorderRadius: "24px"
      };
    }
    const imageLight = createTheme({
      name: "Image",
      common: derived,
      peers: {
        Tooltip: tooltipLight
      },
      self: self$i
    });
    function self$h(vars) {
      const {
        textColorDisabled
      } = vars;
      return {
        iconColorDisabled: textColorDisabled
      };
    }
    const inputNumberLight = createTheme({
      name: "InputNumber",
      common: derived,
      peers: {
        Button: buttonLight,
        Input: inputLight
      },
      self: self$h
    });
    function self$g(vars) {
      const {
        baseColor,
        textColor2,
        bodyColor,
        cardColor,
        dividerColor,
        actionColor,
        scrollbarColor,
        scrollbarColorHover,
        invertedColor
      } = vars;
      return {
        textColor: textColor2,
        textColorInverted: "#FFF",
        color: bodyColor,
        colorEmbedded: actionColor,
        headerColor: cardColor,
        headerColorInverted: invertedColor,
        footerColor: actionColor,
        footerColorInverted: invertedColor,
        headerBorderColor: dividerColor,
        headerBorderColorInverted: invertedColor,
        footerBorderColor: dividerColor,
        footerBorderColorInverted: invertedColor,
        siderBorderColor: dividerColor,
        siderBorderColorInverted: invertedColor,
        siderColor: cardColor,
        siderColorInverted: invertedColor,
        siderToggleButtonBorder: `1px solid ${dividerColor}`,
        siderToggleButtonColor: baseColor,
        siderToggleButtonIconColor: textColor2,
        siderToggleButtonIconColorInverted: textColor2,
        siderToggleBarColor: composite(bodyColor, scrollbarColor),
        siderToggleBarColorHover: composite(bodyColor, scrollbarColorHover),
        __invertScrollbar: "true"
      };
    }
    const layoutLight = createTheme({
      name: "Layout",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight
      },
      self: self$g
    });
    var _common_default$1 = {
      extraFontSize: "12px",
      width: "440px"
    };
    function self$f(vars) {
      const {
        fontWeight,
        iconColorDisabled,
        iconColor,
        fontSizeLarge,
        fontSizeMedium,
        fontSizeSmall,
        heightLarge,
        heightMedium,
        heightSmall,
        borderRadius,
        cardColor,
        tableHeaderColor,
        textColor1,
        textColorDisabled,
        textColor2,
        borderColor,
        hoverColor
      } = vars;
      return {
        ..._common_default$1,
        itemHeightSmall: heightSmall,
        itemHeightMedium: heightMedium,
        itemHeightLarge: heightLarge,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        borderRadius,
        borderColor,
        listColor: cardColor,
        headerColor: composite(cardColor, tableHeaderColor),
        titleTextColor: textColor1,
        titleTextColorDisabled: textColorDisabled,
        extraTextColor: textColor2,
        filterDividerColor: borderColor,
        itemTextColor: textColor2,
        itemTextColorDisabled: textColorDisabled,
        itemColorPending: hoverColor,
        titleFontWeight: fontWeight,
        iconColor,
        iconColorDisabled
      };
    }
    const transferLight$1 = createTheme({
      name: "Transfer",
      common: derived,
      peers: {
        Checkbox: checkboxLight,
        Scrollbar: scrollbarLight,
        Input: inputLight,
        Empty: emptyLight,
        Button: buttonLight
      },
      self: self$f
    });
    function self$e(vars) {
      const {
        textColor2,
        modalColor,
        borderColor,
        fontSize: fontSize2,
        primaryColor
      } = vars;
      return {
        loaderFontSize: fontSize2,
        loaderTextColor: textColor2,
        loaderColor: modalColor,
        loaderBorder: `1px solid ${borderColor}`,
        loadingColor: primaryColor
      };
    }
    const logLight = createTheme({
      name: "Log",
      common: derived,
      peers: {
        Scrollbar: scrollbarLight,
        Code: codeLight
      },
      self: self$e
    });
    function self$d() {
      return {};
    }
    const marqueeLight = {
      name: "Marquee",
      common: derived,
      self: self$d
    };
    function self$c(vars) {
      const {
        boxShadow2
      } = vars;
      return {
        menuBoxShadow: boxShadow2
      };
    }
    const mentionLight = createTheme({
      name: "Mention",
      common: derived,
      peers: {
        InternalSelectMenu: internalSelectMenuLight,
        Input: inputLight
      },
      self: self$c
    });
    var _common_default = {
      titleFontSize: "18px",
      backSize: "22px"
    };
    function self$b(vars) {
      const {
        textColor1,
        textColor2,
        textColor3,
        fontSize: fontSize2,
        fontWeightStrong,
        primaryColorHover,
        primaryColorPressed
      } = vars;
      return {
        ..._common_default,
        titleFontWeight: fontWeightStrong,
        fontSize: fontSize2,
        titleTextColor: textColor1,
        backColor: textColor2,
        backColorHover: primaryColorHover,
        backColorPressed: primaryColorPressed,
        subtitleTextColor: textColor3
      };
    }
    const pageHeaderLight = createTheme({
      name: "PageHeader",
      common: derived,
      self: self$b
    });
    function self$a(vars) {
      return {
        borderRadius: vars.borderRadius
      };
    }
    const themeLight$2 = {
      name: "QrCode",
      common: derived,
      self: self$a
    };
    function self$9(vars) {
      const {
        railColor
      } = vars;
      return {
        itemColor: railColor,
        itemColorActive: "#FFCC33",
        sizeSmall: "16px",
        sizeMedium: "20px",
        sizeLarge: "24px"
      };
    }
    const themeLight$1 = {
      name: "Rate",
      common: derived,
      self: self$9
    };
    function self$8(vars) {
      const {
        heightSmall,
        heightMedium,
        heightLarge,
        borderRadius
      } = vars;
      return {
        color: "#eee",
        colorEnd: "#ddd",
        borderRadius,
        heightSmall,
        heightMedium,
        heightLarge
      };
    }
    const skeletonLight = {
      name: "Skeleton",
      common: derived,
      self: self$8
    };
    var index_cssr_default = c([cB("skeleton", `
 height: 1em;
 width: 100%;
 transition:
 --n-color-start .3s var(--n-bezier),
 --n-color-end .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
 animation: 2s skeleton-loading infinite cubic-bezier(0.36, 0, 0.64, 1);
 background-color: var(--n-color-start);
 `), c("@keyframes skeleton-loading", `
 0% {
 background: var(--n-color-start);
 }
 40% {
 background: var(--n-color-end);
 }
 80% {
 background: var(--n-color-start);
 }
 100% {
 background: var(--n-color-start);
 }
 `)]);
    const skeletonProps = {
      ...useTheme.props,
      text: Boolean,
      round: Boolean,
      circle: Boolean,
      height: [String, Number],
      width: [String, Number],
      size: String,
      repeat: {
        type: Number,
        default: 1
      },
      animated: {
        type: Boolean,
        default: true
      },
      sharp: {
        type: Boolean,
        default: true
      }
    };
    var Skeleton_default = /* @__PURE__ */ defineComponent({
      name: "Skeleton",
      inheritAttrs: false,
      props: skeletonProps,
      setup(props) {
        useHoudini();
        const {
          mergedClsPrefixRef,
          mergedComponentPropsRef
        } = useConfig(props);
        const mergedSizeRef = computed(() => {
          return props.size || mergedComponentPropsRef?.value?.Skeleton?.size;
        });
        const themeRef = useTheme("Skeleton", "-skeleton", index_cssr_default, skeletonLight, props, mergedClsPrefixRef);
        return {
          mergedClsPrefix: mergedClsPrefixRef,
          style: computed(() => {
            const theme = themeRef.value;
            const {
              common: {
                cubicBezierEaseInOut: cubicBezierEaseInOut2
              }
            } = theme;
            const selfThemeVars = theme.self;
            const {
              color,
              colorEnd,
              borderRadius
            } = selfThemeVars;
            let sizeHeight;
            const {
              circle,
              sharp,
              round,
              width,
              height,
              text,
              animated
            } = props;
            const mergedSize = mergedSizeRef.value;
            if (mergedSize !== void 0) sizeHeight = selfThemeVars[createKey("height", mergedSize)];
            const mergedWidth = circle ? width ?? height ?? sizeHeight : width;
            const mergedHeight = (circle ? width ?? height : height) ?? sizeHeight;
            return {
              display: text ? "inline-block" : "",
              verticalAlign: text ? "-0.125em" : "",
              borderRadius: circle ? "50%" : round ? "4096px" : sharp ? "" : borderRadius,
              width: typeof mergedWidth === "number" ? pxfy(mergedWidth) : mergedWidth,
              height: typeof mergedHeight === "number" ? pxfy(mergedHeight) : mergedHeight,
              animation: !animated ? "none" : "",
              "--n-bezier": cubicBezierEaseInOut2,
              "--n-color-start": color,
              "--n-color-end": colorEnd
            };
          })
        };
      },
      render() {
        const {
          repeat: repeatProp,
          style,
          mergedClsPrefix,
          $attrs
        } = this;
        const child = h("div", mergeProps({
          class: `${mergedClsPrefix}-skeleton`,
          style
        }, $attrs));
        if (repeatProp > 1) return openBlock(), createElementBlock(Fragment, {
          key: 1
        }, [normalizeVNode(() => repeat(repeatProp, null).map((_) => [child, "\n"]))], 64);
        return child;
      }
    });
    function self$7(vars) {
      const indicatorColor = "rgba(0, 0, 0, .85)";
      const boxShadow = "0 2px 8px 0 rgba(0, 0, 0, 0.12)";
      const {
        railColor,
        primaryColor,
        baseColor,
        cardColor,
        modalColor,
        popoverColor,
        borderRadius,
        fontSize: fontSize2,
        opacityDisabled
      } = vars;
      return {
        ..._common_default$9,
        fontSize: fontSize2,
        markFontSize: fontSize2,
        railColor,
        railColorHover: railColor,
        fillColor: primaryColor,
        fillColorHover: primaryColor,
        opacityDisabled,
        handleColor: "#FFF",
        dotColor: cardColor,
        dotColorModal: modalColor,
        dotColorPopover: popoverColor,
        handleBoxShadow: "0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)",
        handleBoxShadowHover: "0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)",
        handleBoxShadowActive: "0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)",
        handleBoxShadowFocus: "0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)",
        indicatorColor,
        indicatorBoxShadow: boxShadow,
        indicatorTextColor: baseColor,
        indicatorBorderRadius: borderRadius,
        dotBorder: `2px solid ${railColor}`,
        dotBorderActive: `2px solid ${primaryColor}`,
        dotBoxShadow: ""
      };
    }
    const sliderLight = {
      name: "Slider",
      common: derived,
      self: self$7
    };
    function self$6(vars) {
      const {
        primaryColorHover,
        borderColor
      } = vars;
      return {
        resizableTriggerColorHover: primaryColorHover,
        resizableTriggerColor: borderColor
      };
    }
    const themeLight = {
      name: "Split",
      common: derived,
      self: self$6
    };
    function self$5(vars) {
      const {
        primaryColor,
        opacityDisabled,
        borderRadius,
        textColor3
      } = vars;
      const railOverlayColor = "rgba(0, 0, 0, .14)";
      return {
        ..._common_default$7,
        iconColor: textColor3,
        textColor: "white",
        loadingColor: primaryColor,
        opacityDisabled,
        railColor: railOverlayColor,
        railColorActive: primaryColor,
        buttonBoxShadow: "0 1px 4px 0 rgba(0, 0, 0, 0.3), inset 0 0 1px 0 rgba(0, 0, 0, 0.05)",
        buttonColor: "#FFF",
        railBorderRadiusSmall: borderRadius,
        railBorderRadiusMedium: borderRadius,
        railBorderRadiusLarge: borderRadius,
        buttonBorderRadiusSmall: borderRadius,
        buttonBorderRadiusMedium: borderRadius,
        buttonBorderRadiusLarge: borderRadius,
        boxShadowFocus: `0 0 0 2px ${changeColor(primaryColor, {
          alpha: 0.2
        })}`
      };
    }
    const switchLight = {
      name: "Switch",
      common: derived,
      self: self$5
    };
    function self$4(vars) {
      const {
        textColor3,
        infoColor,
        errorColor,
        successColor,
        warningColor,
        textColor1,
        textColor2,
        railColor,
        fontWeightStrong,
        fontSize: fontSize2
      } = vars;
      return {
        ..._common_default$4,
        contentFontSize: fontSize2,
        titleFontWeight: fontWeightStrong,
        circleBorder: `2px solid ${textColor3}`,
        circleBorderInfo: `2px solid ${infoColor}`,
        circleBorderError: `2px solid ${errorColor}`,
        circleBorderSuccess: `2px solid ${successColor}`,
        circleBorderWarning: `2px solid ${warningColor}`,
        iconColor: textColor3,
        iconColorInfo: infoColor,
        iconColorError: errorColor,
        iconColorSuccess: successColor,
        iconColorWarning: warningColor,
        titleTextColor: textColor1,
        contentTextColor: textColor2,
        metaTextColor: textColor3,
        lineColor: railColor
      };
    }
    const timelineLight = {
      name: "Timeline",
      common: derived,
      self: self$4
    };
    function self$3(vars) {
      const {
        fontWeight,
        fontSizeLarge,
        fontSizeMedium,
        fontSizeSmall,
        heightLarge,
        heightMedium,
        borderRadius,
        cardColor,
        tableHeaderColor,
        textColor1,
        textColorDisabled,
        textColor2,
        textColor3,
        borderColor,
        hoverColor,
        closeColorHover,
        closeColorPressed,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed
      } = vars;
      return {
        ..._common_default$3,
        itemHeightSmall: heightMedium,
        itemHeightMedium: heightMedium,
        itemHeightLarge: heightLarge,
        fontSizeSmall,
        fontSizeMedium,
        fontSizeLarge,
        borderRadius,
        dividerColor: borderColor,
        borderColor,
        listColor: cardColor,
        headerColor: composite(cardColor, tableHeaderColor),
        titleTextColor: textColor1,
        titleTextColorDisabled: textColorDisabled,
        extraTextColor: textColor3,
        extraTextColorDisabled: textColorDisabled,
        itemTextColor: textColor2,
        itemTextColorDisabled: textColorDisabled,
        itemColorPending: hoverColor,
        titleFontWeight: fontWeight,
        closeColorHover,
        closeColorPressed,
        closeIconColor,
        closeIconColorHover,
        closeIconColorPressed
      };
    }
    const transferLight = createTheme({
      name: "Transfer",
      common: derived,
      peers: {
        Checkbox: checkboxLight,
        Scrollbar: scrollbarLight,
        Input: inputLight,
        Empty: emptyLight,
        Button: buttonLight
      },
      self: self$3
    });
    function self$2(vars) {
      const {
        popoverColor,
        boxShadow2,
        borderRadius,
        heightMedium,
        dividerColor,
        textColor2
      } = vars;
      return {
        menuPadding: "4px",
        menuColor: popoverColor,
        menuBoxShadow: boxShadow2,
        menuBorderRadius: borderRadius,
        menuHeight: `calc(${heightMedium} * 7.6)`,
        actionDividerColor: dividerColor,
        actionTextColor: textColor2,
        actionPadding: "8px 12px",
        headerDividerColor: dividerColor,
        headerTextColor: textColor2,
        headerPadding: "8px 12px"
      };
    }
    const treeSelectLight = createTheme({
      name: "TreeSelect",
      common: derived,
      peers: {
        Tree: treeLight,
        Empty: emptyLight,
        InternalSelection: internalSelectionLight
      },
      self: self$2
    });
    const watermarkLight = createTheme({
      name: "Watermark",
      common: derived,
      self(vars) {
        const {
          fontFamily: fontFamily2
        } = vars;
        return {
          fontFamily: fontFamily2
        };
      }
    });
    const buttonGroupLight = {
      name: "ButtonGroup",
      common: derived
    };
    const rowLight = {
      name: "Row",
      common: derived
    };
    const self$1 = () => ({});
    const equationLight = {
      name: "Equation",
      common: derived,
      self: self$1
    };
    const lightTheme = {
      name: "light",
      common: derived,
      Alert: alertLight,
      Anchor: anchorLight,
      AutoComplete: autoCompleteLight,
      Avatar: avatarLight,
      AvatarGroup: avatarGroupLight,
      BackTop: backTopLight,
      Badge: badgeLight,
      Breadcrumb: breadcrumbLight,
      Button: buttonLight,
      ButtonGroup: buttonGroupLight,
      Calendar: calendarLight,
      Card: cardLight,
      Carousel: carouselLight,
      Cascader: cascaderLight,
      Checkbox: checkboxLight,
      Code: codeLight,
      Collapse: collapseLight,
      CollapseTransition: collapseTransitionLight,
      ColorPicker: colorPickerLight,
      DataTable: dataTableLight,
      DatePicker: datePickerLight,
      Descriptions: descriptionsLight,
      Dialog: dialogLight,
      Divider: dividerLight,
      Drawer: drawerLight,
      Dropdown: dropdownLight,
      DynamicInput: dynamicInputLight,
      DynamicTags: dynamicTagsLight,
      Element: elementLight,
      Empty: emptyLight,
      Equation: equationLight,
      Ellipsis: ellipsisLight,
      Flex: flexLight,
      Form: formLight,
      GradientText: gradientTextLight,
      Heatmap: heatmapLight,
      Icon: iconLight,
      IconWrapper: iconWrapperLight,
      Image: imageLight,
      Input: inputLight,
      InputNumber: inputNumberLight,
      InputOtp: inputOtpLight,
      Layout: layoutLight,
      LegacyTransfer: transferLight$1,
      List: listLight,
      LoadingBar: loadingBarLight,
      Log: logLight,
      Menu: menuLight,
      Mention: mentionLight,
      Message: messageLight,
      Modal: modalLight,
      Notification: notificationLight,
      PageHeader: pageHeaderLight,
      Pagination: paginationLight,
      Popconfirm: popconfirmLight,
      Popover: popoverLight,
      Popselect: popselectLight,
      Progress: progressLight,
      QrCode: themeLight$2,
      Radio: radioLight,
      Rate: themeLight$1,
      Row: rowLight,
      Result: resultLight,
      Scrollbar: scrollbarLight,
      Skeleton: skeletonLight,
      Select: selectLight,
      Slider: sliderLight,
      Space: spaceLight,
      Spin: spinLight,
      Statistic: statisticLight,
      Steps: stepsLight,
      Switch: switchLight,
      Table: tableLight,
      Tabs: tabsLight,
      Tag: tagLight,
      Thing: thingLight,
      TimePicker: timePickerLight,
      Timeline: timelineLight,
      Tooltip: tooltipLight,
      Transfer: transferLight,
      Tree: treeLight,
      TreeSelect: treeSelectLight,
      Typography: typographyLight,
      Upload: uploadLight,
      Watermark: watermarkLight,
      Split: themeLight,
      FloatButton: themeLight$3,
      FloatButtonGroup: themeLight$4,
      Marquee: marqueeLight
    };
    const avatarGroupDark = {
      name: "AvatarGroup",
      common: derived$1,
      peers: {
        Avatar: avatarDark
      },
      self: self$1c
    };
    const calendarDark = {
      name: "Calendar",
      common: derived$1,
      peers: {
        Button: buttonDark
      },
      self: self$17
    };
    const carouselDark = {
      name: "Carousel",
      common: derived$1,
      self: self$15
    };
    const collapseTransitionDark = {
      name: "CollapseTransition",
      common: derived$1,
      self: self$$
    };
    const colorPickerDark = {
      name: "ColorPicker",
      common: derived$1,
      peers: {
        Input: inputDark,
        Button: buttonDark
      },
      self: self$_
    };
    const rowDark = {
      name: "Row",
      common: derived$1
    };
    const pageHeaderDark = {
      name: "PageHeader",
      common: derived$1,
      self: self$b
    };
    const floatButtonDark = {
      name: "FloatButton",
      common: derived$1,
      self(vars) {
        const {
          popoverColor,
          textColor2,
          buttonColor2Hover,
          buttonColor2Pressed,
          primaryColor,
          primaryColorHover,
          primaryColorPressed,
          baseColor,
          borderRadius
        } = vars;
        return {
          color: popoverColor,
          textColor: textColor2,
          boxShadow: "0 2px 8px 0px rgba(0, 0, 0, .12)",
          boxShadowHover: "0 2px 12px 0px rgba(0, 0, 0, .18)",
          boxShadowPressed: "0 2px 12px 0px rgba(0, 0, 0, .18)",
          colorHover: buttonColor2Hover,
          colorPressed: buttonColor2Pressed,
          colorPrimary: primaryColor,
          colorPrimaryHover: primaryColorHover,
          colorPrimaryPressed: primaryColorPressed,
          textColorPrimary: baseColor,
          borderRadiusSquare: borderRadius
        };
      }
    };
    const iconDark = {
      name: "IconWrapper",
      common: derived$1,
      self: self$j
    };
    const imageDark = {
      name: "Image",
      common: derived$1,
      peers: {
        Tooltip: tooltipDark
      },
      self: (vars) => {
        const {
          textColor2
        } = vars;
        return {
          toolbarIconColor: textColor2,
          toolbarColor: "rgba(0, 0, 0, .35)",
          toolbarBoxShadow: "none",
          toolbarBorderRadius: "24px"
        };
      }
    };
    const transferDark = {
      name: "Transfer",
      common: derived$1,
      peers: {
        Checkbox: checkboxDark,
        Scrollbar: scrollbarDark,
        Input: inputDark,
        Empty: emptyDark,
        Button: buttonDark
      },
      self(vars) {
        const {
          iconColorDisabled,
          iconColor,
          fontWeight,
          fontSizeLarge,
          fontSizeMedium,
          fontSizeSmall,
          heightLarge,
          heightMedium,
          heightSmall,
          borderRadius,
          inputColor,
          tableHeaderColor,
          textColor1,
          textColorDisabled,
          textColor2,
          hoverColor
        } = vars;
        return {
          ..._common_default$1,
          itemHeightSmall: heightSmall,
          itemHeightMedium: heightMedium,
          itemHeightLarge: heightLarge,
          fontSizeSmall,
          fontSizeMedium,
          fontSizeLarge,
          borderRadius,
          borderColor: "#0000",
          listColor: inputColor,
          headerColor: tableHeaderColor,
          titleTextColor: textColor1,
          titleTextColorDisabled: textColorDisabled,
          extraTextColor: textColor2,
          filterDividerColor: "#0000",
          itemTextColor: textColor2,
          itemTextColorDisabled: textColorDisabled,
          itemColorPending: hoverColor,
          titleFontWeight: fontWeight,
          iconColor,
          iconColorDisabled
        };
      }
    };
    const marqueeDark = {
      name: "Marquee",
      common: derived$1,
      self: self$d
    };
    const qrcodeDark = {
      name: "QrCode",
      common: derived$1,
      self: (vars) => {
        return {
          borderRadius: vars.borderRadius
        };
      }
    };
    const skeletonDark = {
      name: "Skeleton",
      common: derived$1,
      self(vars) {
        const {
          heightSmall,
          heightMedium,
          heightLarge,
          borderRadius
        } = vars;
        return {
          color: "rgba(255, 255, 255, 0.12)",
          colorEnd: "rgba(255, 255, 255, 0.18)",
          borderRadius,
          heightSmall,
          heightMedium,
          heightLarge
        };
      }
    };
    const splitDark = {
      name: "Split",
      common: derived$1
    };
    const equationDark = {
      name: "Equation",
      common: derived$1,
      self: self$1
    };
    const floatButtonGroupDark = {
      name: "FloatButtonGroup",
      common: derived$1,
      self(vars) {
        const {
          popoverColor,
          dividerColor,
          borderRadius
        } = vars;
        return {
          color: popoverColor,
          buttonBorderColor: dividerColor,
          borderRadiusSquare: borderRadius,
          boxShadow: "0 2px 8px 0px rgba(0, 0, 0, .12)"
        };
      }
    };
    const HeatmapDark = {
      name: "Heatmap",
      common: derived$1,
      self(vars) {
        return {
          ...self$k(vars),
          activeColors: ["#0d4429", "#006d32", "#26a641", "#39d353"],
          mininumColor: "rgba(255, 255, 255, 0.1)",
          loadingColorStart: "rgba(255, 255, 255, 0.12)",
          loadingColorEnd: "rgba(255, 255, 255, 0.18)"
        };
      }
    };
    const darkTheme = {
      name: "dark",
      common: derived$1,
      Alert: alertDark,
      Anchor: anchorDark,
      AutoComplete: autoCompleteDark,
      Avatar: avatarDark,
      AvatarGroup: avatarGroupDark,
      BackTop: backTopDark,
      Badge: badgeDark,
      Breadcrumb: breadcrumbDark,
      Button: buttonDark,
      ButtonGroup: buttonGroupDark,
      Calendar: calendarDark,
      Card: cardDark,
      Carousel: carouselDark,
      Cascader: cascaderDark,
      Checkbox: checkboxDark,
      Code: codeDark,
      Collapse: collapseDark,
      CollapseTransition: collapseTransitionDark,
      ColorPicker: colorPickerDark,
      DataTable: dataTableDark,
      DatePicker: datePickerDark,
      Descriptions: descriptionsDark,
      Dialog: dialogDark,
      Divider: dividerDark,
      Drawer: drawerDark,
      Dropdown: dropdownDark,
      DynamicInput: dynamicInputDark,
      DynamicTags: dynamicTagsDark,
      Element: elementDark,
      Empty: emptyDark,
      Ellipsis: ellipsisDark,
      Equation: equationDark,
      Flex: flexDark,
      Form: formItemDark,
      GradientText: gradientTextDark,
      Heatmap: HeatmapDark,
      Icon: iconDark$1,
      IconWrapper: iconDark,
      Image: imageDark,
      Input: inputDark,
      InputNumber: inputNumberDark,
      InputOtp: inputOtpDark,
      LegacyTransfer: transferDark,
      Layout: layoutDark,
      List: listDark$1,
      LoadingBar: loadingBarDark,
      Log: logDark,
      Menu: menuDark,
      Mention: listDark,
      Message: messageDark,
      Modal: modalDark,
      Notification: notificationDark,
      PageHeader: pageHeaderDark,
      Pagination: paginationDark,
      Popconfirm: popconfirmDark,
      Popover: popoverDark,
      Popselect: popselect,
      Progress: progressDark,
      QrCode: qrcodeDark,
      Radio: radioDark,
      Rate: rateDark,
      Result: resultDark,
      Row: rowDark,
      Scrollbar: scrollbarDark,
      Select: selectDark,
      Skeleton: skeletonDark,
      Slider: sliderDark,
      Space: spaceDark,
      Spin: spinDark,
      Statistic: statisticDark,
      Steps: stepsDark,
      Switch: switchDark,
      Table: tableDark,
      Tabs: tabsDark,
      Tag: tagDark,
      Thing: thingDark,
      TimePicker: timePickerDark,
      Timeline: timelineDark,
      Tooltip: tooltipDark,
      Transfer: transferDark$1,
      Tree: treeDark,
      TreeSelect: treeSelectDark,
      Typography: typographyDark,
      Upload: uploadDark,
      Watermark: watermarkDark,
      Split: splitDark,
      FloatButton: floatButtonDark,
      FloatButtonGroup: floatButtonGroupDark,
      Marquee: marqueeDark
    };
    function cssVar(name, fallback = "") {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    }
    const DARK_THEMES = /* @__PURE__ */ new Set(["midnight", "obsidian", "lumei-night"]);
    function isDarkTheme(theme) {
      return DARK_THEMES.has(theme);
    }
    function buildOverrides() {
      return {
        common: {
          // 主色：我们的强调色，Naive 所有 primary 组件都吃它
          primaryColor: cssVar("--a-1", "#e8912f"),
          primaryColorHover: cssVar("--a-2", "#f6b95c"),
          primaryColorPressed: cssVar("--a-1", "#e8912f"),
          primaryColorSuppl: cssVar("--a-2", "#f6b95c"),
          // 语义色
          successColor: cssVar("--ok", "#5f9368"),
          warningColor: cssVar("--warn", "#c9902a"),
          errorColor: cssVar("--err", "#c9614c"),
          infoColor: cssVar("--info", "#5c82ab"),
          // 圆角体系直接用我们的令牌，避免 Naive 的默认圆角和手写部分对不上
          borderRadius: cssVar("--r-s", "10px"),
          borderRadiusSmall: cssVar("--r-xs", "6px"),
          // 文字与表面
          textColorBase: cssVar("--t-1", "#2f2620"),
          textColor1: cssVar("--t-1", "#2f2620"),
          textColor2: cssVar("--t-2", "#6d5f50"),
          textColor3: cssVar("--t-3", "#a1937f"),
          bodyColor: cssVar("--s-bg", "#fdf9f2"),
          cardColor: cssVar("--s-card", "#fffdf8"),
          modalColor: cssVar("--s-card", "#fffdf8"),
          popoverColor: cssVar("--s-card", "#fffdf8"),
          borderColor: cssVar("--s-line", "#eee0c9"),
          dividerColor: cssVar("--s-line-2", "#f7eedd"),
          // 字体：吃页面本身的字体栈，不硬编
          fontFamily: cssVar("--font-ui", "system-ui, sans-serif"),
          fontFamilyMono: "ui-monospace, SFMono-Regular, Menlo, monospace"
        },
        Button: {
          borderRadiusMedium: cssVar("--r-full", "999px")
        },
        Input: {
          borderRadius: cssVar("--r-full", "999px")
        },
        Card: {
          borderRadius: cssVar("--r-l", "20px")
        }
      };
    }
    function currentTheme() {
      return document.documentElement.getAttribute("data-theme") || "lumei";
    }
    const themeState = {
      theme: null,
      // Naive 的 darkTheme / lightTheme 对象
      overrides: {}
    };
    function refresh() {
      const name = currentTheme();
      themeState.theme = isDarkTheme(name) ? darkTheme : lightTheme;
      themeState.overrides = buildOverrides();
    }
    function installLumeiTheme(app) {
      refresh();
      const mo = new MutationObserver(() => {
        const before = themeState.overrides?.common?.primaryColor;
        refresh();
        if (themeState.overrides?.common?.primaryColor !== before) {
          app._instance?.proxy?.$forceUpdate?.();
        }
      });
      mo.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"]
      });
      window.__lumeiRefreshTheme = refresh;
      app.config.globalProperties.$nTheme = themeState;
    }
    function pick$1(name) {
      const v = window.__lumeiLegacy && window.__lumeiLegacy[name];
      if (!v) {
        throw new Error(
          `[lumei] 旧模块 ${name} 还没挂到 window.__lumeiLegacy 上。检查 app/static/js/util.js 是否已加桥接（迁移期必需）。`
        );
      }
      return v;
    }
    const api = new Proxy(
      {},
      { get: (_t, k) => pick$1("api")[k] }
    );
    const bus = new Proxy({}, { get: (_t, k) => pick$1("bus")[k] });
    function toast(msg, kind) {
      return pick$1("toast")(msg, kind);
    }
    const PRE = new Proxy({}, { get: (_t, k) => pick$1("PRE")[k] });
    function confirmBox(opts) {
      return pick$1("confirmBox")(opts);
    }
    function legacy(name) {
      return pick$1(name);
    }
    function whenAuthReady(timeoutMs = 8e3) {
      return new Promise((resolve2) => {
        const t0 = Date.now();
        const tick = () => {
          const L = window.__lumeiLegacy || {};
          if (L.authReady || Date.now() - t0 > timeoutMs) {
            resolve2(!!L.authReady);
            return;
          }
          setTimeout(tick, 60);
        };
        tick();
      });
    }
    const _rdSubs = [];
    let _rdRegistered = false;
    const rdDebug = { snapshots: 0, last: null };
    function attachReaderSnapshot(apply2) {
      _rdSubs.push(apply2);
      if (!_rdRegistered) {
        const fn = window.__lumeiLegacy && window.__lumeiLegacy.attachReader;
        if (typeof fn === "function") {
          fn((st) => {
            rdDebug.snapshots++;
            rdDebug.last = st;
            for (const f of _rdSubs.slice()) {
              try {
                f(st);
              } catch {
              }
            }
          });
          _rdRegistered = true;
        }
        rdDebug.registered = _rdRegistered;
      }
      return () => {
        const i = _rdSubs.indexOf(apply2);
        if (i >= 0) _rdSubs.splice(i, 1);
      };
    }
    function callLegacy(name, ...args) {
      const fn = window.__lumeiLegacy && window.__lumeiLegacy[name];
      if (typeof fn === "function") return fn(...args);
      return void 0;
    }
    if (typeof window !== "undefined") {
      window.__lumeiRdDebug = rdDebug;
    }
    function pick(name) {
      const v = window.__lumeiLegacy && window.__lumeiLegacy[name];
      if (!v) throw new Error(`[lumei] 旧模块 ${name} 未挂到 window.__lumeiLegacy`);
      return v;
    }
    function stagger(root2, sel) {
      return pick("stagger")(root2, sel);
    }
    const _export_sfc = (sfc, props) => {
      const target = sfc.__vccOpts || sfc;
      for (const [key, val] of props) {
        target[key] = val;
      }
      return target;
    };
    const _hoisted_1$7 = { class: "rk-vue" };
    const _hoisted_2$7 = { class: "rk-head" };
    const _hoisted_3$7 = {
      class: "rk-age",
      id: "ranksAge"
    };
    const _hoisted_4$5 = { class: "rk-actions" };
    const _hoisted_5$4 = {
      key: 0,
      class: "rk-err",
      id: "ranksKindsErr"
    };
    const _hoisted_6$4 = {
      key: 1,
      id: "ranksTabs",
      class: "rk-tabs",
      role: "tablist"
    };
    const _hoisted_7$4 = ["data-kind", "aria-selected", "onClick"];
    const _hoisted_8$4 = {
      key: 2,
      class: "rk-desc",
      id: "ranksDesc"
    };
    const _hoisted_9$4 = {
      key: 3,
      class: "rk-body"
    };
    const _hoisted_10$4 = {
      key: 0,
      class: "rk-skel"
    };
    const _hoisted_11$3 = ["data-title", "data-kind", "onClick"];
    const _hoisted_12$3 = { class: "rk-src" };
    const _hoisted_13$3 = {
      key: 0,
      class: "rk-owned",
      title: "这本书已经在你书架里了"
    };
    const _hoisted_14$3 = {
      key: 1,
      class: "rk-go"
    };
    const _hoisted_15$2 = {
      key: 2,
      class: "rk-err"
    };
    const _hoisted_16$2 = {
      key: 3,
      class: "rk-err"
    };
    const _hoisted_17$2 = { class: "rk-foot" };
    const _sfc_main$8 = {
      __name: "RanksPanel",
      setup(__props) {
        const RefreshIcon = {
          template: `<svg viewBox="0 0 20 20" width="15" height="15" fill="none"
    stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
    <path d="M16 10a6 6 0 1 1-1.8-4.3"/><path d="M16 3v3h-3"/></svg>`
        };
        const HUE = { allvisit: 22, weekvisit: 315, allvote: 350, goodnum: 268, monthvisit: 235, postdate: 145, lastupdate: 40 };
        const kinds = /* @__PURE__ */ ref([]);
        const cur = /* @__PURE__ */ ref(PRE.get("ranksKind", "allvisit"));
        const kindsError = /* @__PURE__ */ ref("");
        const items = /* @__PURE__ */ ref([]);
        const sources = /* @__PURE__ */ ref([]);
        const loading = /* @__PURE__ */ ref(false);
        const error = /* @__PURE__ */ ref("");
        const emptyHint = /* @__PURE__ */ ref("");
        const age = /* @__PURE__ */ ref(null);
        const refreshedAt = /* @__PURE__ */ ref(0);
        const staleNow = /* @__PURE__ */ ref(false);
        const onShelf = /* @__PURE__ */ ref(null);
        const shelfPromise = /* @__PURE__ */ ref(null);
        function normTitle(s) {
          return String(s || "").replace(/[《》「」【】\s·・.。、,，:：!！?？'"'"()（）\[\]\-—_~～]/g, "").toLowerCase();
        }
        const isOwned = (t) => !!(onShelf.value && onShelf.value.has(normTitle(t)));
        const hueFor = (k) => HUE[k] ?? 22;
        const medalClass = (i) => i + 1 <= 3 ? ` m${i + 1}` : "";
        function metaOf(it) {
          const meta = [];
          if (it.author) meta.push(it.author);
          if (it.words) meta.push(it.words);
          if (it.status) meta.push(it.status);
          if (it.updated) meta.push(it.updated);
          return meta.join(" · ");
        }
        const curDesc = computed(() => kinds.value.find((k) => k.kind === cur.value)?.desc || "");
        const footLine = computed(() => {
          const n = sources.value.length;
          const names = sources.value.join(" · ");
          const head = n > 1 ? `榜单综合 ${n} 个公开榜单页（${names}）` : n === 1 ? `榜单来自 1 个公开榜单页（${names}）` : "榜单来自公开榜单页";
          return `${head}，后台每 30 分钟自动刷新 ·`;
        });
        const freshness = computed(() => {
          if (age.value == null && !refreshedAt.value) return "";
          let secs = age.value ?? 0;
          if (refreshedAt.value) secs = Math.max(0, (Date.now() - refreshedAt.value) / 1e3);
          if (secs < 90) return "刚刚更新";
          if (secs < 3600) return `${Math.round(secs / 60)} 分钟前更新`;
          if (secs < 86400) return `${Math.round(secs / 3600)} 小时前更新`;
          return `${Math.round(secs / 86400)} 天前更新`;
        });
        function ensureShelf(force) {
          if (!force && onShelf.value) return Promise.resolve(onShelf.value);
          if (shelfPromise.value) return shelfPromise.value;
          shelfPromise.value = api.get("/api/library").then((list) => {
            const s = /* @__PURE__ */ new Set();
            for (const b of Array.isArray(list) ? list : []) {
              const t = normTitle(b && b.title);
              if (t) s.add(t);
            }
            onShelf.value = s;
            return s;
          }).catch(() => {
            onShelf.value = onShelf.value || /* @__PURE__ */ new Set();
            return onShelf.value;
          }).finally(() => {
            shelfPromise.value = null;
          });
          return shelfPromise.value;
        }
        async function loadRanks(kind) {
          if (kind) {
            cur.value = kind;
            PRE.set("ranksKind", kind);
          }
          const want = cur.value;
          loading.value = true;
          error.value = "";
          ensureShelf(false);
          try {
            const d = await api.get(`/api/ranks?kind=${encodeURIComponent(want)}`);
            if (!d || !d.ok) throw new Error(d && d.error || "拿不到榜单");
            if (cur.value !== want) return;
            applyRank(d);
          } catch (e) {
            if (cur.value !== want) return;
            try {
              await new Promise((r) => setTimeout(r, 700));
              if (cur.value !== want) return;
              const d2 = await api.get(`/api/ranks?kind=${encodeURIComponent(want)}`);
              if (!d2 || !d2.ok) throw new Error(d2 && d2.error || "拿不到榜单");
              applyRank(d2);
            } catch (e2) {
              if (cur.value !== want) return;
              error.value = e2.message || String(e2);
              items.value = [];
            }
          } finally {
            if (cur.value === want) loading.value = false;
          }
          requestAnimationFrame(() => {
            const root2 = document.querySelector("[data-vue-ranks]") || document;
            stagger(root2, ".rk-item");
          });
        }
        function applyRank(d) {
          items.value = d.items || [];
          sources.value = Array.isArray(d.sources) ? d.sources : [];
          emptyHint.value = d.empty_hint || "";
          if (typeof d.age === "number") age.value = d.age;
          refreshedAt.value = 0;
          staleNow.value = d.fresh === false;
          if (staleNow.value) scheduleRecheck();
        }
        let recheckTimer = null;
        function scheduleRecheck() {
          clearTimeout(recheckTimer);
          recheckTimer = setTimeout(async () => {
            if (!staleNow.value || !document.querySelector("[data-vue-ranks]")) return;
            const want = cur.value;
            try {
              const d = await api.get(`/api/ranks?kind=${encodeURIComponent(want)}`);
              if (!d || !d.ok || cur.value !== want) return;
              if (d.fresh === false) return;
              applyRank(d);
              requestAnimationFrame(() => {
                const root2 = document.querySelector("[data-vue-ranks]") || document;
                stagger(root2, ".rk-item");
              });
            } catch {
            }
          }, 6e4);
        }
        function onKindChange(k) {
          if (k === cur.value) return;
          loadRanks(k);
        }
        function reload() {
          loadRanks();
        }
        async function refresh2() {
          try {
            await api.post(`/api/ranks/refresh?kind=${encodeURIComponent(cur.value)}`);
            refreshedAt.value = Date.now();
            age.value = 0;
            await loadRanks();
            toast("已刷新到最新");
          } catch (e) {
            toast("刷新失败：" + (e.message || e), "warn");
          }
        }
        function pick2(it) {
          const t = it && it.title;
          if (!t) return;
          const q = document.getElementById("q");
          if (q) q.value = t;
          window.scrollTo({ top: 0, behavior: "smooth" });
          const go = window.__lumeiLegacy && window.__lumeiLegacy.searchFromHash;
          if (go) go(t);
          else bus.emit("ranks:search", t);
        }
        function toShelf() {
          location.hash = "#shelf";
        }
        async function loadKinds() {
          const box = document.getElementById("ranksBox");
          kindsError.value = "";
          let d = null;
          for (let attempt = 0; attempt < 2 && !d; attempt++) {
            try {
              d = await api.get("/api/ranks/kinds");
            } catch {
              if (attempt === 0) await new Promise((r) => setTimeout(r, 600));
            }
          }
          kinds.value = d && d.kinds || [];
          if (box) box.hidden = false;
          if (!kinds.value.length) {
            kindsError.value = d ? "这个版本还没有榜单数据。" : "榜单目录没拿到 —— 可能是网络不通，或访问令牌过期了。";
            return;
          }
          if (!kinds.value.some((k) => k.kind === cur.value)) cur.value = kinds.value[0].kind;
          loadRanks();
        }
        function retryKinds() {
          loadKinds();
        }
        let off1 = null;
        let off2 = null;
        onMounted(async () => {
          await whenAuthReady();
          await loadKinds();
          ensureShelf(true);
          off1 = bus.on("task:done", () => ensureShelf(true));
          off2 = bus.on("shelf:changed", () => ensureShelf(true));
        });
        onUnmounted(() => {
          off1 && off1();
          off2 && off2();
          clearTimeout(recheckTimer);
        });
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock("div", _hoisted_1$7, [
            createBaseVNode("div", _hoisted_2$7, [
              _cache[1] || (_cache[1] = createBaseVNode("h2", { class: "rk-title" }, "热门榜单", -1)),
              createBaseVNode("span", _hoisted_3$7, toDisplayString(freshness.value), 1),
              createBaseVNode("div", _hoisted_4$5, [
                createVNode(unref(Button), {
                  id: "ranksRefresh",
                  size: "small",
                  quaternary: "",
                  loading: loading.value,
                  onClick: refresh2
                }, {
                  icon: withCtx(() => [
                    createVNode(unref(NIcon), null, {
                      default: withCtx(() => [
                        createVNode(RefreshIcon)
                      ]),
                      _: 1
                    })
                  ]),
                  default: withCtx(() => [
                    _cache[0] || (_cache[0] = createTextVNode(" 刷新 ", -1))
                  ]),
                  _: 1
                }, 8, ["loading"])
              ])
            ]),
            !kinds.value.length ? (openBlock(), createElementBlock("div", _hoisted_5$4, [
              createTextVNode(toDisplayString(kindsError.value || "榜单暂时取不到。") + " ", 1),
              createVNode(unref(Button), {
                id: "ranksKindsRetry",
                size: "tiny",
                quaternary: "",
                onClick: retryKinds
              }, {
                default: withCtx(() => [..._cache[2] || (_cache[2] = [
                  createTextVNode("重试", -1)
                ])]),
                _: 1
              })
            ])) : createCommentVNode("", true),
            kinds.value.length ? (openBlock(), createElementBlock("div", _hoisted_6$4, [
              (openBlock(true), createElementBlock(Fragment, null, renderList(kinds.value, (k) => {
                return openBlock(), createElementBlock("button", {
                  key: k.kind,
                  class: normalizeClass(["rk-tab", { on: k.kind === cur.value }]),
                  "data-kind": k.kind,
                  role: "tab",
                  "aria-selected": k.kind === cur.value,
                  type: "button",
                  onClick: ($event) => onKindChange(k.kind)
                }, toDisplayString(k.label), 11, _hoisted_7$4);
              }), 128))
            ])) : createCommentVNode("", true),
            curDesc.value ? (openBlock(), createElementBlock("p", _hoisted_8$4, toDisplayString(curDesc.value), 1)) : createCommentVNode("", true),
            kinds.value.length ? (openBlock(), createElementBlock("div", _hoisted_9$4, [
              loading.value && !items.value.length ? (openBlock(), createElementBlock("div", _hoisted_10$4, [
                (openBlock(), createElementBlock(Fragment, null, renderList(6, (i) => {
                  return createVNode(unref(Skeleton_default), {
                    key: i,
                    height: "46px",
                    sharp: false
                  });
                }), 64))
              ])) : items.value.length ? (openBlock(), createBlock(TransitionGroup, {
                key: 1,
                name: "rk-item",
                tag: "div",
                class: "rk-list",
                id: "ranksList"
              }, {
                default: withCtx(() => [
                  (openBlock(true), createElementBlock(Fragment, null, renderList(items.value, (it, i) => {
                    return openBlock(), createElementBlock("button", {
                      key: it.title + i,
                      class: normalizeClass(["rk-item", { owned: isOwned(it.title) }]),
                      "data-title": it.title,
                      "data-kind": it.kind,
                      type: "button",
                      onClick: ($event) => pick2(it)
                    }, [
                      createBaseVNode("span", {
                        class: normalizeClass(["rk-no", medalClass(i)])
                      }, toDisplayString(i + 1), 3),
                      createBaseVNode("span", {
                        class: "rk-ttl",
                        style: normalizeStyle({ "--h": hueFor(it.kind) })
                      }, [
                        createBaseVNode("b", null, toDisplayString(it.title), 1),
                        createBaseVNode("em", null, toDisplayString(metaOf(it) || " "), 1)
                      ], 4),
                      createBaseVNode("span", _hoisted_12$3, toDisplayString(it.source_display || it.source || ""), 1),
                      isOwned(it.title) ? (openBlock(), createElementBlock("span", _hoisted_13$3, " ✓ 已在书架 ")) : (openBlock(), createElementBlock("span", _hoisted_14$3, "找这本 ›"))
                    ], 10, _hoisted_11$3);
                  }), 128))
                ]),
                _: 1
              })) : !loading.value ? (openBlock(), createElementBlock("div", _hoisted_15$2, [
                createTextVNode(toDisplayString(emptyHint.value || "这个榜单暂时没有内容。") + " ", 1),
                createVNode(unref(Button), {
                  size: "tiny",
                  quaternary: "",
                  onClick: reload
                }, {
                  default: withCtx(() => [..._cache[3] || (_cache[3] = [
                    createTextVNode("重试", -1)
                  ])]),
                  _: 1
                })
              ])) : createCommentVNode("", true),
              error.value && items.value.length ? (openBlock(), createElementBlock("div", _hoisted_16$2, [
                createTextVNode(" 刷新失败：" + toDisplayString(error.value) + " ", 1),
                createVNode(unref(Button), {
                  size: "tiny",
                  quaternary: "",
                  onClick: reload
                }, {
                  default: withCtx(() => [..._cache[4] || (_cache[4] = [
                    createTextVNode("重试", -1)
                  ])]),
                  _: 1
                })
              ])) : createCommentVNode("", true)
            ])) : createCommentVNode("", true),
            createBaseVNode("div", _hoisted_17$2, [
              createTextVNode(toDisplayString(footLine.value) + " ", 1),
              createBaseVNode("button", {
                class: "rk-link",
                id: "ranksToLib",
                type: "button",
                onClick: toShelf
              }, "去看我的书架 ›")
            ])
          ]);
        };
      }
    };
    const RanksPanel = /* @__PURE__ */ _export_sfc(_sfc_main$8, [["__scopeId", "data-v-7e1734ff"]]);
    const _hoisted_1$6 = ["src"];
    const _hoisted_2$6 = { class: "t" };
    const _hoisted_3$6 = { class: "a" };
    const _sfc_main$7 = {
      __name: "BookCover",
      props: {
        /** 真封面外链（可空 —— 空了就用渐变色块兜底） */
        cover: { type: String, default: "" },
        /** 兼容旧签名：直接传色相数字，强制走渐变 */
        hue: { type: Number, default: null },
        title: { type: String, default: "" },
        author: { type: String, default: "" },
        lg: { type: Boolean, default: false }
      },
      setup(__props) {
        const props = __props;
        const hasImg = /* @__PURE__ */ ref(false);
        const proxySrc = computed(() => {
          if (props.hue !== null) return "";
          const u = (props.cover || "").trim();
          if (!u) return "";
          return `/api/cover?u=${encodeURIComponent(u)}`;
        });
        watch(proxySrc, (v) => {
          hasImg.value = !!v;
        }, { immediate: true });
        const hue = computed(() => {
          if (props.hue !== null) return (props.hue % 360 + 360) % 360;
          return (props.title || "").length * 37 % 360;
        });
        const gradientStyle = computed(() => {
          if (hasImg.value) return void 0;
          const h2 = hue.value;
          const c1 = `hsl(${h2} 58% 50%)`;
          const c2 = `hsl(${(h2 + 38) % 360} 54% 34%)`;
          return { background: `linear-gradient(150deg,${c1},${c2})` };
        });
        const shortTitle = computed(() => (props.title || "?").slice(0, 7));
        const shortAuthor = computed(() => (props.author || "佚名").slice(0, 6));
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock("div", {
            class: normalizeClass(["cover", { lg: __props.lg, "has-img": hasImg.value }]),
            style: normalizeStyle(gradientStyle.value)
          }, [
            proxySrc.value ? (openBlock(), createElementBlock("img", {
              key: 0,
              src: proxySrc.value,
              alt: "",
              loading: "lazy",
              decoding: "async",
              onError: _cache[0] || (_cache[0] = ($event) => hasImg.value = false)
            }, null, 40, _hoisted_1$6)) : createCommentVNode("", true),
            createBaseVNode("div", _hoisted_2$6, toDisplayString(shortTitle.value), 1),
            createBaseVNode("div", _hoisted_3$6, toDisplayString(shortAuthor.value), 1)
          ], 6);
        };
      }
    };
    const _hoisted_1$5 = { class: "wrap" };
    const _hoisted_2$5 = { class: "filters" };
    const _hoisted_3$5 = {
      id: "shelfStat",
      class: "shelf-stat"
    };
    const _hoisted_4$4 = {
      key: 0,
      class: "shelfgrid",
      id: "shelfList"
    };
    const _hoisted_5$3 = {
      key: 1,
      class: "shelfgrid",
      id: "shelfList"
    };
    const _hoisted_6$3 = ["data-id"];
    const _hoisted_7$3 = { class: "info" };
    const _hoisted_8$3 = { class: "by" };
    const _hoisted_9$3 = { class: "prog" };
    const _hoisted_10$3 = { class: "lb" };
    const _hoisted_11$2 = { class: "bar" };
    const _hoisted_12$2 = { class: "lb" };
    const _hoisted_13$2 = { class: "bar" };
    const _hoisted_14$2 = { class: "acts" };
    const _sfc_main$6 = {
      __name: "ShelfPanel",
      setup(__props) {
        const books = /* @__PURE__ */ ref([]);
        const loading = /* @__PURE__ */ ref(true);
        const statText = computed(() => books.value.length ? `共 ${books.value.length} 本` : "");
        function readPct(b) {
          const total = b.total || 0;
          const pos = b.position || {};
          if (!total) return 0;
          return Math.min(100, ((pos.index || 1) - 1 + (pos.percent || 0)) / total * 100);
        }
        function cachePct(b) {
          const total = b.total || 0;
          if (!total) return 0;
          return Math.min(100, (b.cached || 0) / total * 100);
        }
        let gotData = false;
        async function reload() {
          loading.value = true;
          armSafety();
          try {
            await legacy("loadShelf")();
          } catch (e) {
            toast("读取书架失败：" + e.message, "err");
            loading.value = false;
          }
        }
        const onLoaded = (list) => {
          gotData = true;
          books.value = Array.isArray(list) ? list : [];
          loading.value = false;
          clearTimeout(safety);
        };
        let safety = null;
        function armSafety() {
          clearTimeout(safety);
          safety = setTimeout(() => {
            loading.value = false;
          }, 15e3);
        }
        async function onAct(b, a) {
          if (a === "read") bus.emit("shelf:read", b);
          else if (a === "export") {
            bus.emit("shelf:export", { library_id: b.id, title: b.title, author: b.author });
          } else if (a === "cache") {
            bus.emit("shelf:cache", { id: b.id, title: b.title });
          } else if (a === "del") {
            const yes = await confirmBox({
              title: "移出书架",
              message: `把《${b.title}》移出书架？已经缓存的正文章节会一起删掉，下次要重新去网上抓。`,
              okText: "移出",
              danger: true
            });
            if (!yes) return;
            try {
              await api.del("/api/library/" + b.id);
              toast("已移出书架");
              reload();
            } catch (e) {
              toast("移出失败：" + e.message, "err");
            }
          }
        }
        onMounted(async () => {
          await whenAuthReady();
          bus.on("shelf:loaded", onLoaded);
          loading.value = true;
          setTimeout(() => {
            if (!gotData) reload();
          }, 200);
        });
        onUnmounted(() => {
          bus.off("shelf:loaded", onLoaded);
          clearTimeout(safety);
        });
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock("div", _hoisted_1$5, [
            createBaseVNode("div", _hoisted_2$5, [
              _cache[1] || (_cache[1] = createBaseVNode("div", { class: "shelf-h" }, "我的书架", -1)),
              createBaseVNode("span", _hoisted_3$5, toDisplayString(statText.value), 1),
              _cache[2] || (_cache[2] = createBaseVNode("div", { class: "spacer" }, null, -1)),
              createVNode(unref(Button), {
                id: "btnShelfReload",
                size: "small",
                quaternary: "",
                loading: loading.value,
                onClick: reload
              }, {
                default: withCtx(() => [..._cache[0] || (_cache[0] = [
                  createTextVNode(" 刷新 ", -1)
                ])]),
                _: 1
              }, 8, ["loading"])
            ]),
            loading.value && !books.value.length ? (openBlock(), createElementBlock("div", _hoisted_4$4, [
              (openBlock(), createElementBlock(Fragment, null, renderList(4, (i) => {
                return createBaseVNode("div", {
                  key: i,
                  class: "shelf sk"
                }, [..._cache[3] || (_cache[3] = [
                  createStaticVNode('<div class="sk-cover" data-v-f5c78a01></div><div class="info" data-v-f5c78a01><div class="sk-line w60" data-v-f5c78a01></div><div class="sk-line w40" data-v-f5c78a01></div><div class="sk-line w80 tall" data-v-f5c78a01></div></div>', 2)
                ])]);
              }), 64))
            ])) : (openBlock(), createElementBlock("div", _hoisted_5$3, [
              (openBlock(true), createElementBlock(Fragment, null, renderList(books.value, (b, i) => {
                return openBlock(), createElementBlock("div", {
                  key: b.id,
                  class: "shelf",
                  "data-id": b.id,
                  style: normalizeStyle({ "--mo-i": i })
                }, [
                  createVNode(_sfc_main$7, {
                    cover: b.cover,
                    title: b.title,
                    author: b.author
                  }, null, 8, ["cover", "title", "author"]),
                  createBaseVNode("div", _hoisted_7$3, [
                    createBaseVNode("h4", null, toDisplayString(b.title), 1),
                    createBaseVNode("div", _hoisted_8$3, toDisplayString(b.author || "作者未知") + " · " + toDisplayString(b.source_display || b.source || ""), 1),
                    createBaseVNode("div", _hoisted_9$3, [
                      createBaseVNode("div", null, [
                        createBaseVNode("div", _hoisted_10$3, [
                          createBaseVNode("span", null, "读到 " + toDisplayString(b.position?.index || 1) + "/" + toDisplayString(b.total || "?") + " 章", 1),
                          createBaseVNode("span", null, toDisplayString(readPct(b).toFixed(0)) + "%", 1)
                        ]),
                        createBaseVNode("div", _hoisted_11$2, [
                          createBaseVNode("i", {
                            style: normalizeStyle({ width: readPct(b) + "%" })
                          }, null, 4)
                        ])
                      ]),
                      createBaseVNode("div", null, [
                        createBaseVNode("div", _hoisted_12$2, [
                          createBaseVNode("span", null, "已缓存 " + toDisplayString(b.cached || 0) + " 章", 1),
                          createBaseVNode("span", null, toDisplayString(cachePct(b).toFixed(0)) + "%", 1)
                        ]),
                        createBaseVNode("div", _hoisted_13$2, [
                          createBaseVNode("i", {
                            style: normalizeStyle({ width: cachePct(b) + "%", background: "var(--ok)" })
                          }, null, 4)
                        ])
                      ])
                    ]),
                    createBaseVNode("div", _hoisted_14$2, [
                      createVNode(unref(Button), {
                        size: "small",
                        type: "primary",
                        "data-a": "read",
                        onClick: ($event) => onAct(b, "read")
                      }, {
                        default: withCtx(() => [
                          createTextVNode(toDisplayString(readPct(b) > 1 ? "继续阅读" : "开始阅读"), 1)
                        ]),
                        _: 2
                      }, 1032, ["onClick"]),
                      createVNode(unref(Button), {
                        size: "small",
                        "data-a": "cache",
                        onClick: ($event) => onAct(b, "cache")
                      }, {
                        default: withCtx(() => [..._cache[4] || (_cache[4] = [
                          createTextVNode("缓存全书", -1)
                        ])]),
                        _: 1
                      }, 8, ["onClick"]),
                      createVNode(unref(Button), {
                        size: "small",
                        "data-a": "export",
                        onClick: ($event) => onAct(b, "export")
                      }, {
                        default: withCtx(() => [..._cache[5] || (_cache[5] = [
                          createTextVNode("导出", -1)
                        ])]),
                        _: 1
                      }, 8, ["onClick"]),
                      createVNode(unref(Button), {
                        size: "small",
                        quaternary: "",
                        "data-a": "del",
                        onClick: ($event) => onAct(b, "del")
                      }, {
                        default: withCtx(() => [..._cache[6] || (_cache[6] = [
                          createTextVNode("移除", -1)
                        ])]),
                        _: 1
                      }, 8, ["onClick"])
                    ])
                  ])
                ], 12, _hoisted_6$3);
              }), 128))
            ])),
            createBaseVNode("div", {
              id: "shelfEmpty",
              class: normalizeClass(["empty", { hidden: books.value.length > 0 || loading.value }])
            }, [..._cache[7] || (_cache[7] = [
              createBaseVNode("div", {
                class: "empty-art",
                "aria-hidden": "true"
              }, null, -1),
              createBaseVNode("h3", null, "书架空空，噜噜睡得正香", -1),
              createBaseVNode("p", null, "在「发现」里点「开始阅读」，书就会落到这里 —— 之后打开秒进，断网也能看。", -1)
            ])], 2)
          ]);
        };
      }
    };
    const ShelfPanel = /* @__PURE__ */ _export_sfc(_sfc_main$6, [["__scopeId", "data-v-f5c78a01"]]);
    const _hoisted_1$4 = { class: "wrap" };
    const _hoisted_2$4 = { class: "filters" };
    const _hoisted_3$4 = {
      key: 0,
      id: "fileList"
    };
    const _hoisted_4$3 = {
      key: 1,
      id: "fileList"
    };
    const _hoisted_5$2 = ["data-ext"];
    const _hoisted_6$2 = ["data-ext", "innerHTML"];
    const _hoisted_7$2 = { class: "nm" };
    const _hoisted_8$2 = ["title"];
    const _hoisted_9$2 = { class: "acts" };
    const _hoisted_10$2 = ["href"];
    const _sfc_main$5 = {
      __name: "FilesPanel",
      setup(__props) {
        const ICONS = {
          txt: "M4 2h8l4 4v12H4zM12 2v4h4",
          epub: "M4 2h9l4 4v12H4zM13 2v4h4M7 10h7M7 13h7",
          html: "M12 2a10 10 0 100 20 10 10 0 000-20M2 12h20M12 2c2.5 2.7 3.8 6.2 3.8 10S14.5 19.3 12 22M12 2C9.5 4.7 8.2 8.2 8.2 12S9.5 19.3 12 22"
        };
        function fmtIcon(ext) {
          const p2 = ICONS[ext] || "M4 2h8l4 4v12H4z";
          return `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="${p2}"/></svg>`;
        }
        const files = /* @__PURE__ */ ref([]);
        const loading = /* @__PURE__ */ ref(true);
        const fmt = /* @__PURE__ */ ref(PRE.get("fmt", "txt"));
        function onFmt(v) {
          PRE.set("fmt", v);
        }
        const fmtSize = (n) => legacy("fmtSize")(n);
        const fmtTime = (t) => legacy("fmtTime")(t);
        function downloadUrl(f) {
          return api.url("/api/file/" + encodeURIComponent(f.name));
        }
        function onOpen(f) {
          window.open(downloadUrl(f), "_blank");
        }
        async function onDel(f) {
          const yes = await confirmBox({
            title: "删除文件",
            message: `删除 ${f.name}？这个操作不能撤销。`,
            okText: "删除",
            danger: true
          });
          if (!yes) return;
          try {
            await api.del("/api/file/" + encodeURIComponent(f.name));
            toast("已删除");
            reload();
          } catch (e) {
            toast("删除失败：" + e.message, "err");
          }
        }
        let gotData = false;
        async function reload() {
          loading.value = true;
          armSafety();
          try {
            await legacy("loadFiles")();
          } catch (e) {
            toast("读取文件失败：" + e.message, "err");
            loading.value = false;
          }
        }
        const onLoaded = (list) => {
          gotData = true;
          files.value = Array.isArray(list) ? list : [];
          loading.value = false;
          clearTimeout(safety);
        };
        let safety = null;
        function armSafety() {
          clearTimeout(safety);
          safety = setTimeout(() => {
            loading.value = false;
          }, 15e3);
        }
        onMounted(async () => {
          await whenAuthReady();
          bus.on("files:loaded", onLoaded);
          bus.on("task:done", onTaskDone);
          loading.value = true;
          setTimeout(() => {
            if (!gotData) reload();
          }, 200);
        });
        function onTaskDone(t) {
          if (t && t.kind === "download") reload();
        }
        onUnmounted(() => {
          bus.off("files:loaded", onLoaded);
          bus.off("task:done", onTaskDone);
          clearTimeout(safety);
        });
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock("div", _hoisted_1$4, [
            createBaseVNode("div", _hoisted_2$4, [
              _cache[4] || (_cache[4] = createBaseVNode("div", { class: "files-h" }, "导出文件", -1)),
              _cache[5] || (_cache[5] = createBaseVNode("div", { class: "spacer" }, null, -1)),
              _cache[6] || (_cache[6] = createBaseVNode("label", {
                class: "sr",
                for: "fmtPick"
              }, "导出格式", -1)),
              withDirectives(createBaseVNode("select", {
                id: "fmtPick",
                "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => fmt.value = $event),
                class: "fmt-select",
                onChange: _cache[1] || (_cache[1] = ($event) => onFmt(fmt.value))
              }, [..._cache[2] || (_cache[2] = [
                createBaseVNode("option", { value: "txt" }, "TXT（哪里都能开）", -1),
                createBaseVNode("option", { value: "epub" }, "EPUB（Kindle / 阅读器）", -1),
                createBaseVNode("option", { value: "html" }, "HTML（自带小阅读器的单文件）", -1)
              ])], 544), [
                [vModelSelect, fmt.value]
              ]),
              createVNode(unref(Button), {
                id: "btnFilesReload",
                size: "small",
                quaternary: "",
                loading: loading.value,
                onClick: reload
              }, {
                default: withCtx(() => [..._cache[3] || (_cache[3] = [
                  createTextVNode(" 刷新 ", -1)
                ])]),
                _: 1
              }, 8, ["loading"])
            ]),
            loading.value && !files.value.length ? (openBlock(), createElementBlock("div", _hoisted_3$4, [
              (openBlock(), createElementBlock(Fragment, null, renderList(3, (i) => {
                return createBaseVNode("div", {
                  key: i,
                  class: "fsk"
                }, [..._cache[7] || (_cache[7] = [
                  createStaticVNode('<div class="sk-ic" data-v-3663db34></div><div class="sk-col" data-v-3663db34><div class="sk-line w60" data-v-3663db34></div><div class="sk-line w40" data-v-3663db34></div></div><div class="sk-acts" data-v-3663db34><div class="sk-btn" data-v-3663db34></div><div class="sk-btn" data-v-3663db34></div></div>', 3)
                ])]);
              }), 64))
            ])) : (openBlock(), createElementBlock("div", _hoisted_4$3, [
              (openBlock(true), createElementBlock(Fragment, null, renderList(files.value, (f) => {
                return openBlock(), createElementBlock("div", {
                  key: f.name,
                  class: "file",
                  "data-ext": f.ext
                }, [
                  createBaseVNode("div", {
                    class: "ic",
                    "data-ext": f.ext,
                    innerHTML: fmtIcon(f.ext)
                  }, null, 8, _hoisted_6$2),
                  createBaseVNode("div", _hoisted_7$2, [
                    createBaseVNode("b", {
                      title: f.name
                    }, toDisplayString(f.name), 9, _hoisted_8$2),
                    createBaseVNode("span", null, toDisplayString((f.ext || "").toUpperCase()) + " · " + toDisplayString(fmtSize(f.size)) + " · " + toDisplayString(fmtTime(f.mtime)), 1)
                  ]),
                  createBaseVNode("div", _hoisted_9$2, [
                    f.ext === "html" ? (openBlock(), createBlock(unref(Button), {
                      key: 0,
                      size: "small",
                      "data-open": f.name,
                      onClick: ($event) => onOpen(f)
                    }, {
                      default: withCtx(() => [..._cache[8] || (_cache[8] = [
                        createTextVNode(" 打开看 ", -1)
                      ])]),
                      _: 1
                    }, 8, ["data-open", "onClick"])) : createCommentVNode("", true),
                    createBaseVNode("a", {
                      class: "btn sm",
                      href: downloadUrl(f),
                      download: ""
                    }, "下载", 8, _hoisted_10$2),
                    createVNode(unref(Button), {
                      size: "small",
                      quaternary: "",
                      "data-del": f.name,
                      onClick: ($event) => onDel(f)
                    }, {
                      default: withCtx(() => [..._cache[9] || (_cache[9] = [
                        createTextVNode("删除", -1)
                      ])]),
                      _: 1
                    }, 8, ["data-del", "onClick"])
                  ])
                ], 8, _hoisted_5$2);
              }), 128))
            ])),
            createBaseVNode("div", {
              id: "fileEmpty",
              class: normalizeClass(["empty", { hidden: files.value.length > 0 || loading.value }])
            }, [..._cache[10] || (_cache[10] = [
              createBaseVNode("div", {
                class: "empty-art",
                "aria-hidden": "true"
              }, null, -1),
              createBaseVNode("h3", null, "还没导出过", -1),
              createBaseVNode("p", null, "在书籍卡片上点「导出」，或者在书架里导出整本 —— 打包好就能带走。", -1)
            ])], 2)
          ]);
        };
      }
    };
    const FilesPanel = /* @__PURE__ */ _export_sfc(_sfc_main$5, [["__scopeId", "data-v-3663db34"]]);
    const _hoisted_1$3 = { class: "lu-discover" };
    const _hoisted_2$3 = ["innerHTML"];
    const _hoisted_3$3 = { class: "nl-head" };
    const _hoisted_4$2 = { id: "netLiveTitle" };
    const _hoisted_5$1 = {
      class: "nl-sub",
      id: "netLiveSub"
    };
    const _hoisted_6$1 = { class: "t" };
    const _hoisted_7$1 = {
      key: 0,
      class: "x"
    };
    const _hoisted_8$1 = { class: "switch" };
    const _hoisted_9$1 = ["checked"];
    const _hoisted_10$1 = {
      class: "srcchips",
      id: "srcChips"
    };
    const _hoisted_11$1 = ["data-src", "onClick"];
    const _hoisted_12$1 = {
      class: "grid",
      id: "results"
    };
    const _hoisted_13$1 = {
      key: 0,
      class: "fuzzy auth"
    };
    const _hoisted_14$1 = { class: "ft" };
    const _hoisted_15$1 = {
      key: 1,
      class: "fuzzy"
    };
    const _hoisted_16$1 = { class: "ft" };
    const _hoisted_17$1 = ["data-gk"];
    const _hoisted_18$1 = { class: "head" };
    const _hoisted_19$1 = { class: "meta" };
    const _hoisted_20$1 = { class: "by" };
    const _hoisted_21 = { class: "desc" };
    const _hoisted_22 = {
      key: 1,
      class: "no-intro"
    };
    const _hoisted_23 = { class: "tags" };
    const _hoisted_24 = { class: "acts" };
    const _hoisted_25 = { class: "sources" };
    const _hoisted_26 = { class: "nm" };
    const _hoisted_27 = { class: "n" };
    const _hoisted_28 = ["data-u", "onClick"];
    const _hoisted_29 = ["data-u", "onClick"];
    const _hoisted_30 = ["innerHTML"];
    const _sfc_main$4 = {
      __name: "DiscoverPanel",
      setup(__props) {
        const books = /* @__PURE__ */ ref([]);
        const searching = /* @__PURE__ */ ref(false);
        const onlyOk = /* @__PURE__ */ ref(true);
        const sources = /* @__PURE__ */ ref([]);
        const srcOn = /* @__PURE__ */ ref(/* @__PURE__ */ new Set());
        const fuzzy = /* @__PURE__ */ ref(false);
        const confirmed = /* @__PURE__ */ ref("");
        const statHTML = /* @__PURE__ */ ref("");
        const steps = /* @__PURE__ */ ref([]);
        const netTitle = /* @__PURE__ */ ref("正在联网找书…");
        const netSub = /* @__PURE__ */ ref("");
        const netDone = /* @__PURE__ */ ref(false);
        const netFolded = /* @__PURE__ */ ref(false);
        const showFilters = /* @__PURE__ */ ref(false);
        const confirmHTML = /* @__PURE__ */ ref("");
        const open = /* @__PURE__ */ ref(/* @__PURE__ */ new Set());
        const spinEl = /* @__PURE__ */ ref(null);
        const stepsEl = /* @__PURE__ */ ref(null);
        const list = computed(
          () => onlyOk.value ? books.value.filter((b) => (b.sources || []).some((s) => s.readable || s.available)) : books.value
        );
        const byAuthor = computed(
          () => !fuzzy.value && list.value.some((b) => (b.sources || []).some((s) => s.by_author))
        );
        const showHomeEmpty = computed(() => {
          if (searching.value) return false;
          if (list.value.length) return false;
          return true;
        });
        const emptyTitle = computed(() => {
          if (!books.value.length) return "说个书名，噜噜就跑去找";
          return `搜到 ${books.value.length} 本，但都没通过验证`;
        });
        const emptyText = computed(() => {
          if (!books.value.length) {
            return "每本都先验一遍，真能读到正文才敢说「能读」。";
          }
          return "关掉上面的「只看能读的」看看原始结果，或者点开卡片看每个来源的状态 —— 有的站点目录能开、正文抓不到，卡片上会写清楚。";
        });
        function toRanks() {
          location.hash = "#ranks";
        }
        function groupKey(b) {
          return `${(b.title || "").trim()}\0${(b.author || "").trim()}`;
        }
        function displayTitle(b) {
          return b.display_title || b.title;
        }
        function siteNames(b) {
          return [...new Set((b.sources || []).map((s) => s.source_display || s.source).filter(Boolean))].join("、");
        }
        function uOf(s) {
          return `${s && s.source || ""}|${s && s.url || ""}`;
        }
        function best(b) {
          return (b.sources || []).find((s) => s.readable) || (b.sources || [])[0] || {};
        }
        function srcPill(s) {
          if (s.readable) return { cls: "ok", text: `✓ 可读 · ${s.chapter_count} 章` };
          if (s.sample_ok === false) return { cls: "warn", text: "目录在，正文抓不到" };
          if (s.available) return { cls: "mute", text: `目录 ${s.chapter_count} 章 · 正文未验证` };
          if (s.available === false) return { cls: "bad", text: `✕ ${s.note || "打不开"}` };
          return { cls: "mute", text: "未验证" };
        }
        function tocNote(s) {
          return s && s.chapter_note ? { cls: "warn", text: `⚠ ${s.chapter_note}` } : null;
        }
        function tagsOf(b) {
          const out = [];
          const sampledBad = (b.sources || []).some((s) => s.sample_ok === false);
          const sampledGood = (b.sources || []).some((s) => s.sample_ok === true);
          if (b.readable_count) out.push({ cls: "ok", text: `${b.readable_count} 个来源可读` });
          else if (sampledBad) out.push({ cls: "warn", text: "目录能开，但正文抓不到" });
          else if (b.available_count) out.push({ cls: "mute", text: `${b.available_count} 个来源目录可达 · 正文未验证` });
          else out.push({ cls: "bad", text: "暂无可用来源" });
          if (b.chapter_count) out.push({ cls: "mute", text: `最多 ${b.chapter_count} 章` });
          if (sampledGood && b.sample_chars) out.push({ cls: "ok", text: "正文已验证" });
          if (b.source_count > 1) out.push({ cls: "mute", text: `${b.source_count} 个站点收录` });
          return out;
        }
        const HIT = /发现可用来源|来源库命中|来源库已更新|收录/;
        function stepCls(s) {
          if (s.ok === false) return "bad";
          return HIT.test(s.title) ? "hit" : "";
        }
        function onOnlyOk(e) {
          const v = e.target.checked;
          onlyOk.value = v;
          legacy("setOnlyOk")(v);
        }
        function toggleSrc(name) {
          legacy("toggleSource")(name);
        }
        function clearSearch() {
          legacy("clearSearch")();
        }
        function toggleOpen(b) {
          const k = groupKey(b);
          const s = new Set(open.value);
          if (s.has(k)) s.delete(k);
          else s.add(k);
          open.value = s;
        }
        function onAct(act, b, s) {
          if (!s || !s.url) return;
          if (act === "read") bus.emit("book:read", s);
          if (act === "dl") bus.emit("book:export", { src: s, book: b });
        }
        function applyState(st) {
          if (!st) return;
          books.value = st.books || [];
          searching.value = !!st.searching;
          onlyOk.value = st.onlyOk !== false;
          fuzzy.value = !!st.fuzzy;
          confirmed.value = st.confirmed || "";
          statHTML.value = st.statHTML || "";
          showFilters.value = !!st.filtersVisible;
          confirmHTML.value = st.confirmHTML || "";
          steps.value = st.steps || [];
          netTitle.value = st.netTitle || "正在联网找书…";
          netSub.value = st.netSub || "";
          netDone.value = !!st.netDone;
          if (typeof st.netFolded === "boolean") netFolded.value = st.netFolded;
          if (st.sources) sources.value = st.sources;
          if (st.srcOn) srcOn.value = new Set(st.srcOn);
          nextTick(() => {
            const root2 = document.querySelector("[data-vue-discover]");
            if (root2) legacy("stagger")(root2, ".book");
          });
        }
        onMounted(async () => {
          await whenAuthReady();
          bus.on("discover:state", applyState);
          legacy("attachDiscover")(applyState);
        });
        onUnmounted(() => {
          bus.off("discover:state", applyState);
          legacy("detachDiscover")();
        });
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock("div", _hoisted_1$3, [
            createBaseVNode("div", {
              class: "statbar",
              id: "statbar",
              innerHTML: statHTML.value
            }, null, 8, _hoisted_2$3),
            createBaseVNode("div", {
              class: normalizeClass(["netlive", { hidden: !steps.value.length, done: netDone.value, folded: netFolded.value }]),
              id: "netLive",
              "aria-live": "polite"
            }, [
              createBaseVNode("div", _hoisted_3$3, [
                createBaseVNode("span", {
                  class: normalizeClass(["nl-spin", { on: !netDone.value }]),
                  ref_key: "spinEl",
                  ref: spinEl
                }, null, 2),
                createBaseVNode("b", _hoisted_4$2, toDisplayString(netTitle.value), 1),
                createBaseVNode("span", _hoisted_5$1, toDisplayString(netSub.value), 1),
                _cache[1] || (_cache[1] = createBaseVNode("span", { class: "grow" }, null, -1)),
                createVNode(unref(Button), {
                  id: "netLiveToggle",
                  size: "tiny",
                  quaternary: "",
                  onClick: _cache[0] || (_cache[0] = ($event) => netFolded.value = !netFolded.value)
                }, {
                  default: withCtx(() => [
                    createTextVNode(toDisplayString(netFolded.value ? "展开" : "收起"), 1)
                  ]),
                  _: 1
                })
              ]),
              createBaseVNode("ol", {
                class: "nl-steps",
                id: "netLiveSteps",
                ref_key: "stepsEl",
                ref: stepsEl
              }, [
                (openBlock(true), createElementBlock(Fragment, null, renderList(steps.value, (s, i) => {
                  return openBlock(), createElementBlock("li", {
                    key: i,
                    class: normalizeClass(stepCls(s))
                  }, [
                    _cache[2] || (_cache[2] = createBaseVNode("span", { class: "d" }, null, -1)),
                    createBaseVNode("span", _hoisted_6$1, toDisplayString(s.title), 1),
                    s.detail ? (openBlock(), createElementBlock("span", _hoisted_7$1, toDisplayString(s.detail), 1)) : createCommentVNode("", true)
                  ], 2);
                }), 128))
              ], 512)
            ], 2),
            createBaseVNode("div", {
              class: normalizeClass(["filters", { hidden: !showFilters.value }]),
              id: "filters"
            }, [
              createBaseVNode("label", _hoisted_8$1, [
                createBaseVNode("input", {
                  type: "checkbox",
                  id: "onlyOk",
                  checked: onlyOk.value,
                  onChange: onOnlyOk
                }, null, 40, _hoisted_9$1),
                _cache[3] || (_cache[3] = createBaseVNode("span", { class: "track" }, null, -1)),
                _cache[4] || (_cache[4] = createTextVNode("只看能读的 ", -1))
              ]),
              _cache[6] || (_cache[6] = createBaseVNode("span", { class: "vline" }, null, -1)),
              createBaseVNode("div", _hoisted_10$1, [
                (openBlock(true), createElementBlock(Fragment, null, renderList(sources.value, (s) => {
                  return openBlock(), createElementBlock("button", {
                    key: s.name,
                    class: normalizeClass(["chip", { on: srcOn.value.has(s.name) }]),
                    "data-src": s.name,
                    type: "button",
                    onClick: ($event) => toggleSrc(s.name)
                  }, toDisplayString(s.display), 11, _hoisted_11$1);
                }), 128))
              ]),
              _cache[7] || (_cache[7] = createBaseVNode("div", { class: "spacer" }, null, -1)),
              createVNode(unref(Button), {
                id: "btnClearSearch",
                size: "small",
                quaternary: "",
                onClick: clearSearch
              }, {
                default: withCtx(() => [..._cache[5] || (_cache[5] = [
                  createTextVNode("清空结果", -1)
                ])]),
                _: 1
              })
            ], 2),
            createBaseVNode("div", _hoisted_12$1, [
              searching.value && !list.value.length ? (openBlock(), createElementBlock(Fragment, { key: 0 }, renderList(6, (i) => {
                return createBaseVNode("div", {
                  key: i,
                  class: "skl"
                }, [..._cache[8] || (_cache[8] = [
                  createStaticVNode('<div class="b cv" data-v-baa453b6></div><div class="col" data-v-baa453b6><div class="b ln" style="width:52%;" data-v-baa453b6></div><div class="b ln" style="width:32%;height:10px;" data-v-baa453b6></div><div class="b ln" style="width:92%;height:10px;" data-v-baa453b6></div><div class="b ln" style="width:70%;height:10px;" data-v-baa453b6></div></div>', 2)
                ])]);
              }), 64)) : list.value.length ? (openBlock(), createElementBlock(Fragment, { key: 1 }, [
                byAuthor.value ? (openBlock(), createElementBlock("div", _hoisted_13$1, [
                  _cache[9] || (_cache[9] = createBaseVNode("span", { class: "fi" }, "✍️", -1)),
                  createBaseVNode("div", _hoisted_14$1, [
                    createBaseVNode("b", null, "按作者找到了 " + toDisplayString(books.value.length) + " 本", 1),
                    createBaseVNode("span", null, "「" + toDisplayString(confirmed.value) + "」是作者名，下面是 ta 的作品 —— 书名里当然不含作者名，这是对的。", 1)
                  ])
                ])) : fuzzy.value ? (openBlock(), createElementBlock("div", _hoisted_15$1, [
                  _cache[10] || (_cache[10] = createBaseVNode("span", { class: "fi" }, "🤔", -1)),
                  createBaseVNode("div", _hoisted_16$1, [
                    createBaseVNode("b", null, "没找到确切的《" + toDisplayString(confirmed.value) + "》", 1),
                    createBaseVNode("span", null, "下面这 " + toDisplayString(books.value.length) + " 本是「沾边」结果 —— 名字里带这几个字，但不一定是你要的那本。补上作者名一起搜会准很多。", 1)
                  ])
                ])) : createCommentVNode("", true),
                (openBlock(true), createElementBlock(Fragment, null, renderList(list.value, (b, i) => {
                  return openBlock(), createElementBlock("div", {
                    key: groupKey(b),
                    class: normalizeClass(["book", { open: open.value.has(groupKey(b)) }]),
                    "data-gk": groupKey(b),
                    style: normalizeStyle({ "--mo-i": i })
                  }, [
                    createBaseVNode("div", _hoisted_18$1, [
                      createVNode(_sfc_main$7, {
                        cover: b.cover,
                        hue: b.hue,
                        title: displayTitle(b),
                        author: b.author
                      }, null, 8, ["cover", "hue", "title", "author"]),
                      createBaseVNode("div", _hoisted_19$1, [
                        createBaseVNode("h3", null, toDisplayString(displayTitle(b)), 1),
                        createBaseVNode("div", _hoisted_20$1, toDisplayString(b.author || "作者未知"), 1),
                        createBaseVNode("div", _hoisted_21, [
                          b.intro ? (openBlock(), createElementBlock(Fragment, { key: 0 }, [
                            createTextVNode(toDisplayString(b.intro), 1)
                          ], 64)) : (openBlock(), createElementBlock("span", _hoisted_22, "收录于 " + toDisplayString(siteNames(b)), 1))
                        ]),
                        createBaseVNode("div", _hoisted_23, [
                          (openBlock(true), createElementBlock(Fragment, null, renderList(tagsOf(b), (t, ti) => {
                            return openBlock(), createElementBlock("span", {
                              key: ti,
                              class: normalizeClass(["pill", t.cls])
                            }, toDisplayString(t.text), 3);
                          }), 128))
                        ])
                      ])
                    ]),
                    createBaseVNode("div", _hoisted_24, [
                      createVNode(unref(Button), {
                        size: "small",
                        type: "primary",
                        "data-act": "read",
                        "data-u": uOf(best(b)),
                        onClick: ($event) => onAct("read", b, best(b))
                      }, {
                        default: withCtx(() => [..._cache[11] || (_cache[11] = [
                          createTextVNode("开始阅读", -1)
                        ])]),
                        _: 1
                      }, 8, ["data-u", "onClick"]),
                      createVNode(unref(Button), {
                        size: "small",
                        "data-act": "toggle",
                        onClick: ($event) => toggleOpen(b)
                      }, {
                        default: withCtx(() => [
                          createTextVNode(" 来源 " + toDisplayString(b.source_count) + " ▾ ", 1)
                        ]),
                        _: 2
                      }, 1032, ["onClick"]),
                      createVNode(unref(Button), {
                        size: "small",
                        "data-act": "dl",
                        "data-u": uOf(best(b)),
                        title: "导出文件",
                        onClick: ($event) => onAct("dl", b, best(b))
                      }, {
                        default: withCtx(() => [..._cache[12] || (_cache[12] = [
                          createTextVNode("↧", -1)
                        ])]),
                        _: 1
                      }, 8, ["data-u", "onClick"])
                    ]),
                    createBaseVNode("div", _hoisted_25, [
                      (openBlock(true), createElementBlock(Fragment, null, renderList(b.sources, (s, si) => {
                        return openBlock(), createElementBlock("div", {
                          key: si,
                          class: "srow"
                        }, [
                          createBaseVNode("span", _hoisted_26, toDisplayString(s.source_display || s.source), 1),
                          createBaseVNode("span", {
                            class: normalizeClass(["pill", srcPill(s).cls])
                          }, toDisplayString(srcPill(s).text), 3),
                          tocNote(s) ? (openBlock(), createElementBlock("span", {
                            key: 0,
                            class: normalizeClass(["pill", tocNote(s).cls])
                          }, toDisplayString(tocNote(s).text), 3)) : createCommentVNode("", true),
                          _cache[13] || (_cache[13] = createBaseVNode("span", { class: "grow" }, null, -1)),
                          createBaseVNode("span", _hoisted_27, toDisplayString(s.probe_ms ? s.probe_ms + "ms" : ""), 1),
                          s.readable || s.available ? (openBlock(), createElementBlock("button", {
                            key: 1,
                            class: "mini pri",
                            "data-act": "read",
                            "data-u": uOf(s),
                            onClick: ($event) => onAct("read", b, s)
                          }, "阅读", 8, _hoisted_28)) : createCommentVNode("", true),
                          createBaseVNode("button", {
                            class: "mini",
                            "data-act": "dl",
                            "data-u": uOf(s),
                            onClick: ($event) => onAct("dl", b, s)
                          }, "导出", 8, _hoisted_29)
                        ]);
                      }), 128))
                    ])
                  ], 14, _hoisted_17$1);
                }), 128))
              ], 64)) : createCommentVNode("", true)
            ]),
            createBaseVNode("div", {
              id: "homeEmpty",
              class: normalizeClass(["empty", { hidden: !showHomeEmpty.value, "no-books": !books.value.length }])
            }, [
              _cache[14] || (_cache[14] = createBaseVNode("div", {
                class: "empty-art",
                "aria-hidden": "true"
              }, null, -1)),
              createBaseVNode("h3", null, toDisplayString(emptyTitle.value), 1),
              createBaseVNode("p", null, toDisplayString(emptyText.value), 1),
              !books.value.length ? (openBlock(), createElementBlock("button", {
                key: 0,
                id: "homeToRanks",
                class: "btn ghost sm",
                type: "button",
                onClick: toRanks
              }, "去推荐逛逛 ›")) : createCommentVNode("", true)
            ], 2),
            createBaseVNode("div", {
              id: "confirmBox",
              innerHTML: confirmHTML.value
            }, null, 8, _hoisted_30)
          ]);
        };
      }
    };
    const DiscoverPanel = /* @__PURE__ */ _export_sfc(_sfc_main$4, [["__scopeId", "data-v-baa453b6"]]);
    const _hoisted_1$2 = { class: "rd-top" };
    const _hoisted_2$2 = { class: "ttl" };
    const _hoisted_3$2 = { id: "rdTitle" };
    const _hoisted_4$1 = { id: "rdSub" };
    const _sfc_main$3 = {
      __name: "ReaderTop",
      setup(__props) {
        const title = /* @__PURE__ */ ref("—");
        const sub = /* @__PURE__ */ ref("—");
        const progress = /* @__PURE__ */ ref(0);
        function applyState(st) {
          if (!st) return;
          if (typeof st.title === "string") title.value = st.title || "—";
          if (typeof st.sub === "string") sub.value = st.sub;
          if (typeof st.progress === "number") progress.value = st.progress;
        }
        const call2 = callLegacy;
        let off = null;
        onMounted(() => {
          nextTick(() => {
            off = attachReaderSnapshot(applyState);
          });
        });
        onUnmounted(() => {
          if (off) off();
        });
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock(Fragment, null, [
            createBaseVNode("div", {
              class: "rd-prog",
              id: "rdProg",
              style: normalizeStyle({ width: progress.value * 100 + "%" })
            }, null, 4),
            createBaseVNode("div", _hoisted_1$2, [
              createBaseVNode("button", {
                class: "rd-btn",
                id: "rdBack",
                title: "退出 (Esc)",
                "aria-label": "退出",
                onClick: _cache[0] || (_cache[0] = ($event) => unref(call2)("rdBack"))
              }, "←"),
              _cache[5] || (_cache[5] = createBaseVNode("span", {
                class: "rd-capy-mark",
                "aria-hidden": "true"
              }, null, -1)),
              createBaseVNode("div", _hoisted_2$2, [
                createBaseVNode("b", _hoisted_3$2, toDisplayString(title.value || "—"), 1),
                createBaseVNode("small", _hoisted_4$1, toDisplayString(sub.value), 1)
              ]),
              createBaseVNode("button", {
                class: "rd-btn",
                id: "rdTocBtn",
                title: "目录 (T)",
                "aria-label": "目录",
                onClick: _cache[1] || (_cache[1] = ($event) => unref(call2)("rdTogglePanel", "toc"))
              }, "☰"),
              createBaseVNode("button", {
                class: "rd-btn",
                id: "rdCacheBtn",
                title: "缓存全书",
                "aria-label": "缓存全书",
                onClick: _cache[2] || (_cache[2] = ($event) => unref(call2)("rdCache"))
              }, "⤓"),
              createBaseVNode("button", {
                class: "rd-btn",
                id: "rdSetBtn",
                title: "设置 (S)",
                "aria-label": "设置",
                onClick: _cache[3] || (_cache[3] = ($event) => unref(call2)("rdTogglePanel", "set"))
              }, "Aa"),
              createBaseVNode("button", {
                class: "rd-btn",
                id: "rdExportBtn",
                title: "导出",
                "aria-label": "导出",
                onClick: _cache[4] || (_cache[4] = ($event) => unref(call2)("rdExport"))
              }, "↧")
            ])
          ], 64);
        };
      }
    };
    const _hoisted_1$1 = { class: "rd-info" };
    const _hoisted_2$1 = {
      class: "ch",
      id: "rdChap"
    };
    const _hoisted_3$1 = {
      class: "pct",
      id: "rdPct"
    };
    const _sfc_main$2 = {
      __name: "ReaderBottom",
      setup(__props) {
        const chap = /* @__PURE__ */ ref("—");
        const pct = /* @__PURE__ */ ref("0%");
        function applyState(st) {
          if (!st) return;
          if (typeof st.chap === "string") chap.value = st.chap;
          if (typeof st.pct === "string") pct.value = st.pct;
        }
        let off = null;
        onMounted(() => {
          nextTick(() => {
            off = attachReaderSnapshot(applyState);
          });
        });
        onUnmounted(() => {
          if (off) off();
        });
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock("div", _hoisted_1$1, [
            createBaseVNode("span", _hoisted_2$1, toDisplayString(chap.value), 1),
            _cache[0] || (_cache[0] = createBaseVNode("span", { class: "sep" }, " · ", -1)),
            createBaseVNode("span", _hoisted_3$1, toDisplayString(pct.value), 1)
          ]);
        };
      }
    };
    const _hoisted_1 = { class: "rd-panel-search" };
    const _hoisted_2 = ["innerHTML"];
    const _hoisted_3 = { class: "list" };
    const _hoisted_4 = { class: "rd-set-row" };
    const _hoisted_5 = ["innerHTML"];
    const _hoisted_6 = { class: "rd-set-row" };
    const _hoisted_7 = {
      class: "rd-stepper",
      id: "rdFsRow"
    };
    const _hoisted_8 = {
      class: "v",
      id: "rdFsV"
    };
    const _hoisted_9 = { class: "rd-set-row" };
    const _hoisted_10 = {
      class: "rd-seg",
      id: "rdLhRow"
    };
    const _hoisted_11 = ["data-lh", "onClick"];
    const _hoisted_12 = { class: "rd-set-row" };
    const _hoisted_13 = {
      class: "rd-seg",
      id: "rdFfRow"
    };
    const _hoisted_14 = ["data-ff", "onClick"];
    const _hoisted_15 = { class: "rd-set-row" };
    const _hoisted_16 = {
      class: "rd-seg",
      id: "rdWRow"
    };
    const _hoisted_17 = ["data-w", "onClick"];
    const _hoisted_18 = { class: "rd-set-row" };
    const _hoisted_19 = {
      class: "rd-seg",
      id: "rdModeRow"
    };
    const _hoisted_20 = ["data-mode", "onClick"];
    const _sfc_main$1 = {
      __name: "ReaderPanels",
      setup(__props) {
        const call2 = callLegacy;
        const LH = [{ v: 1.6, label: "紧凑" }, { v: 1.85, label: "标准" }, { v: 2.2, label: "宽松" }];
        const FF = [{ v: "serif", label: "宋体" }, { v: "sans", label: "黑体" }, { v: "kai", label: "楷体" }];
        const W = [{ v: 32, label: "窄" }, { v: 40, label: "中" }, { v: 50, label: "宽" }];
        const MODE = [
          { v: "slide", label: "左右平移" },
          { v: "flip", label: "仿真翻页" },
          { v: "scroll", label: "上下滚动" }
        ];
        const tocOpen = /* @__PURE__ */ ref(false);
        const setOpen = /* @__PURE__ */ ref(false);
        const tocHTML = /* @__PURE__ */ ref("");
        const themesHTML = /* @__PURE__ */ ref("");
        const fs = /* @__PURE__ */ ref(19);
        const lh = /* @__PURE__ */ ref(1.85);
        const ff = /* @__PURE__ */ ref("serif");
        const w = /* @__PURE__ */ ref(40);
        const mode = /* @__PURE__ */ ref("slide");
        function applyState(st) {
          if (!st) return;
          if (typeof st.tocOpen === "boolean") tocOpen.value = st.tocOpen;
          if (typeof st.setOpen === "boolean") setOpen.value = st.setOpen;
          if (typeof st.tocHTML === "string") tocHTML.value = st.tocHTML;
          if (typeof st.themesHTML === "string") themesHTML.value = st.themesHTML;
          if (typeof st.fs === "number") fs.value = st.fs;
          if (st.lh != null) lh.value = st.lh;
          if (typeof st.ff === "string") ff.value = st.ff;
          if (st.w != null) w.value = st.w;
          if (st.modes && typeof st.modes.mode === "string") mode.value = st.modes.mode;
        }
        function onTocQuery(e) {
          call2("rdFilterToc", e.target.value);
        }
        function onTocClick(e) {
          const a = e.target.closest("a");
          if (!a) return;
          e.preventDefault();
          call2("rdGoChapter", a.dataset.i);
        }
        function onThemeClick(e) {
          const b = e.target.closest("button[data-th]");
          if (b) call2("rdSetTheme", b.dataset.th);
        }
        let off = null;
        onMounted(() => {
          nextTick(() => {
            off = attachReaderSnapshot(applyState);
          });
        });
        onUnmounted(() => {
          if (off) off();
        });
        return (_ctx, _cache) => {
          return openBlock(), createElementBlock(Fragment, null, [
            createBaseVNode("aside", {
              class: normalizeClass(["rd-panel", { on: tocOpen.value }]),
              id: "rdToc"
            }, [
              createBaseVNode("header", null, [
                _cache[4] || (_cache[4] = createBaseVNode("h4", null, "目录", -1)),
                createBaseVNode("button", {
                  class: "rd-btn",
                  id: "rdTocClose",
                  "aria-label": "关闭目录",
                  onClick: _cache[0] || (_cache[0] = ($event) => unref(call2)("rdClosePanels"))
                }, "✕")
              ]),
              createBaseVNode("div", _hoisted_1, [
                createBaseVNode("input", {
                  type: "search",
                  id: "rdTocQ",
                  placeholder: "搜索章节名…",
                  onInput: onTocQuery
                }, null, 32)
              ]),
              createBaseVNode("div", {
                class: "list",
                id: "rdTocList",
                innerHTML: tocHTML.value,
                onClick: onTocClick
              }, null, 8, _hoisted_2)
            ], 2),
            createBaseVNode("aside", {
              class: normalizeClass(["rd-panel right", { on: setOpen.value }]),
              id: "rdSet"
            }, [
              createBaseVNode("header", null, [
                _cache[5] || (_cache[5] = createBaseVNode("h4", null, "阅读设置", -1)),
                createBaseVNode("button", {
                  class: "rd-btn",
                  id: "rdSetClose",
                  "aria-label": "关闭设置",
                  onClick: _cache[1] || (_cache[1] = ($event) => unref(call2)("rdClosePanels"))
                }, "✕")
              ]),
              createBaseVNode("div", _hoisted_3, [
                createBaseVNode("div", _hoisted_4, [
                  _cache[6] || (_cache[6] = createBaseVNode("div", { class: "gl" }, "配色", -1)),
                  createBaseVNode("div", {
                    class: "rd-thermos",
                    id: "rdThemes",
                    innerHTML: themesHTML.value,
                    onClick: onThemeClick
                  }, null, 8, _hoisted_5)
                ]),
                createBaseVNode("div", _hoisted_6, [
                  _cache[7] || (_cache[7] = createBaseVNode("div", { class: "gl" }, "字号", -1)),
                  createBaseVNode("div", _hoisted_7, [
                    createBaseVNode("button", {
                      "data-fs": "-1",
                      "aria-label": "减小字号",
                      onClick: _cache[2] || (_cache[2] = ($event) => unref(call2)("rdSetOpt", "fs", -1))
                    }, "A－"),
                    createBaseVNode("span", _hoisted_8, toDisplayString(fs.value) + "px", 1),
                    createBaseVNode("button", {
                      "data-fs": "1",
                      "aria-label": "增大字号",
                      onClick: _cache[3] || (_cache[3] = ($event) => unref(call2)("rdSetOpt", "fs", 1))
                    }, "A＋")
                  ])
                ]),
                createBaseVNode("div", _hoisted_9, [
                  _cache[8] || (_cache[8] = createBaseVNode("div", { class: "gl" }, "行距", -1)),
                  createBaseVNode("div", _hoisted_10, [
                    (openBlock(), createElementBlock(Fragment, null, renderList(LH, (o) => {
                      return createBaseVNode("button", {
                        key: o.v,
                        "data-lh": o.v,
                        class: normalizeClass({ on: +lh.value === +o.v }),
                        onClick: ($event) => unref(call2)("rdSetOpt", "lh", o.v)
                      }, toDisplayString(o.label), 11, _hoisted_11);
                    }), 64))
                  ])
                ]),
                createBaseVNode("div", _hoisted_12, [
                  _cache[9] || (_cache[9] = createBaseVNode("div", { class: "gl" }, "字体", -1)),
                  createBaseVNode("div", _hoisted_13, [
                    (openBlock(), createElementBlock(Fragment, null, renderList(FF, (o) => {
                      return createBaseVNode("button", {
                        key: o.v,
                        "data-ff": o.v,
                        class: normalizeClass({ on: ff.value === o.v }),
                        onClick: ($event) => unref(call2)("rdSetOpt", "ff", o.v)
                      }, toDisplayString(o.label), 11, _hoisted_14);
                    }), 64))
                  ])
                ]),
                createBaseVNode("div", _hoisted_15, [
                  _cache[10] || (_cache[10] = createBaseVNode("div", { class: "gl" }, "每行宽度", -1)),
                  createBaseVNode("div", _hoisted_16, [
                    (openBlock(), createElementBlock(Fragment, null, renderList(W, (o) => {
                      return createBaseVNode("button", {
                        key: o.v,
                        "data-w": o.v,
                        class: normalizeClass({ on: +w.value === +o.v }),
                        onClick: ($event) => unref(call2)("rdSetOpt", "w", o.v)
                      }, toDisplayString(o.label), 11, _hoisted_17);
                    }), 64))
                  ])
                ]),
                createBaseVNode("div", _hoisted_18, [
                  _cache[11] || (_cache[11] = createBaseVNode("div", { class: "gl" }, "翻页方式", -1)),
                  createBaseVNode("div", _hoisted_19, [
                    (openBlock(), createElementBlock(Fragment, null, renderList(MODE, (o) => {
                      return createBaseVNode("button", {
                        key: o.v,
                        "data-mode": o.v,
                        class: normalizeClass({ on: mode.value === o.v }),
                        onClick: ($event) => unref(call2)("rdSetOpt", "mode", o.v)
                      }, toDisplayString(o.label), 11, _hoisted_20);
                    }), 64))
                  ])
                ]),
                _cache[12] || (_cache[12] = createStaticVNode('<div class="rd-set-row" data-v-562433e7><div class="gl" data-v-562433e7>快捷键</div><div class="rd-kbd" data-v-562433e7><kbd data-v-562433e7>←</kbd><kbd data-v-562433e7>→</kbd> 翻页 · <kbd data-v-562433e7>空格</kbd> 下翻 · <kbd data-v-562433e7>[</kbd><kbd data-v-562433e7>]</kbd> 上下章<br data-v-562433e7><kbd data-v-562433e7>T</kbd> 目录 · <kbd data-v-562433e7>S</kbd> 设置 · <kbd data-v-562433e7>F</kbd> 沉浸 · <kbd data-v-562433e7>Esc</kbd> 退出<br data-v-562433e7> 手机上：点屏幕<b data-v-562433e7>左右两侧</b>翻页，点<b data-v-562433e7>中间</b>唤出工具栏；也可以左右滑动。 </div></div>', 1))
              ])
            ], 2)
          ], 64);
        };
      }
    };
    const ReaderPanels = /* @__PURE__ */ _export_sfc(_sfc_main$1, [["__scopeId", "data-v-562433e7"]]);
    const _sfc_main = {
      __name: "App",
      props: {
        /** 这个 app 实例负责渲染哪个组件（见 main.js 的 MOUNTS） */
        only: { type: String, default: "" }
      },
      setup(__props) {
        const props = __props;
        const REGISTRY = {
          RanksPanel,
          ShelfPanel,
          FilesPanel,
          DiscoverPanel,
          ReaderTop: _sfc_main$3,
          ReaderBottom: _sfc_main$2,
          ReaderPanels
        };
        const comp = computed(() => REGISTRY[props.only] || RanksPanel);
        return (_ctx, _cache) => {
          return openBlock(), createBlock(unref(ConfigProvider_default), {
            theme: unref(themeState).theme,
            "theme-overrides": unref(themeState).overrides
          }, {
            default: withCtx(() => [
              (openBlock(), createBlock(resolveDynamicComponent(comp.value)))
            ]),
            _: 1
          }, 8, ["theme", "theme-overrides"]);
        };
      }
    };
    const MOUNTS = [
      { name: "RanksPanel", sel: "[data-vue-ranks]" },
      { name: "ShelfPanel", sel: "[data-vue-shelf]" },
      { name: "FilesPanel", sel: "[data-vue-files]" },
      { name: "DiscoverPanel", sel: "[data-vue-discover]" },
      // 阅读器外壳拆成三个容器 —— 这不是设计过度，是布局契约逼出来的：
      // `#reader` 是纵向 flex，`.rd-prog/.rd-top` 在 `.rd-stage` **之前**、
      // `.rd-bottom` 在**之后**，而 Vue 没法把节点插到"容器之后、下一个兄弟之前"。
      // 两个面板是 `.rd-stage` 内绝对定位的子元素，另起一个容器。
      { name: "ReaderTop", sel: "[data-vue-rdtop]" },
      { name: "ReaderPanels", sel: "[data-vue-rdpanels]" },
      { name: "ReaderBottom", sel: "[data-vue-rdbottom]" }
    ];
    let mounted = 0;
    for (const m of MOUNTS) {
      const hosts = document.querySelectorAll(m.sel);
      hosts.forEach((host) => {
        const target = host.firstElementChild || host;
        const app = createApp(_sfc_main, { only: m.name });
        installLumeiTheme(app);
        app.mount(target);
        mounted++;
      });
    }
    if (!mounted) {
      console.info("[lumei] 没有找到 Vue 挂载点，跳过（该页尚未迁移）");
    }
  }
});
export default require_vue_app();
