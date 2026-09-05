#!/usr/bin/env python3
"""GIMP Agent Bridge: a GIMP 3 plug-in that exposes GIMP to gimp-agent-mcp.

Runs inside GIMP's own Python. Listens on 127.0.0.1 only, requires the token
written to ``<GIMP config dir>/agent-bridge.json`` on every request, and
executes all GIMP work on the plug-in's main thread via the GLib main loop.

Start it from Filters > Development > Start Agent Bridge, or let the MCP
server launch GIMP with the bridge already running.
"""

import base64
import contextlib
import io
import os
import socket
import sys
import tempfile
import threading
import traceback

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
gi.require_version("Babl", "0.1")
from gi.repository import Gegl, Gimp, Gio, GLib, GObject  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_bridge_core as core  # noqa: E402

ITEM_TYPE_NAMES = {
    "GimpItem",
    "GimpDrawable",
    "GimpLayer",
    "GimpGroupLayer",
    "GimpTextLayer",
    "GimpChannel",
    "GimpLayerMask",
    "GimpSelection",
    "GimpPath",
}

INT_TYPES = {"gint", "guint", "gint64", "guint64", "glong", "gulong", "gint8", "guint8", "gshort", "gushort"}
FLOAT_TYPES = {"gdouble", "gfloat"}


class BridgeError(Exception):
    pass


# --------------------------------------------------------------------------- serialisation


_NAMESPACES = {"Gimp": Gimp, "Gegl": Gegl, "GObject": GObject, "GLib": GLib, "Gio": Gio}


def _enum_pytype(gtype):
    """Find the Python class for a GEnum GType.

    PyGObject only creates the class once the namespace attribute has been touched, and GEGL
    registers many operation enums at runtime with no introspection data at all, so fall back
    to the namespace lookup and then to gi's own enum wrapper.
    """
    pytype = gtype.pytype
    if pytype is not None:
        return pytype
    name = gtype.name
    for prefix, module in _NAMESPACES.items():
        if name.startswith(prefix):
            with contextlib.suppress(Exception):
                cls = getattr(module, name[len(prefix) :])
                if cls is not None:
                    return cls
    with contextlib.suppress(Exception):
        from gi import _gi

        return _gi.enum_add(gtype)
    return None


def _enum_members(gtype):
    try:
        pytype = _enum_pytype(gtype)
        if pytype is not None and hasattr(pytype, "__enum_values__"):
            return list(pytype.__enum_values__.values())
    except Exception:
        pass
    return []


def _enum_nicks(gtype):
    return [m.value_nick for m in _enum_members(gtype)]


def _serialise(value):
    """Convert GIMP/GObject values into JSON-safe structures."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Gimp.Image):
        return {"type": "GimpImage", "id": value.get_id(), "name": value.get_name()}
    if isinstance(value, Gimp.Item):
        return {"type": value.__gtype__.name, "id": value.get_id(), "name": value.get_name()}
    if isinstance(value, Gegl.Color):
        return core.color_to_hex(tuple(value.get_rgba()))
    if isinstance(value, Gio.File):
        return value.get_path()
    if isinstance(value, GObject.GEnum):
        return value.value_nick
    if isinstance(value, GObject.GFlags):
        return int(value)
    if isinstance(value, (list, tuple)):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serialise(v) for k, v in value.items()}
    if isinstance(value, Gimp.ValueArray):
        return [_serialise(value.index(i)) for i in range(value.length())]
    if isinstance(value, GObject.Value):
        try:
            return _serialise(value.get_value())
        except Exception:
            return repr(value)
    return repr(value)


def _describe_pspec(pspec):
    gtype = pspec.value_type
    info = {
        "name": pspec.name,
        "type": gtype.name,
        "blurb": pspec.get_blurb() or "",
    }
    try:
        default = pspec.get_default_value()
        info["default"] = _serialise(default)
    except Exception:
        pass
    for attr in ("minimum", "maximum"):
        if hasattr(pspec, attr):
            try:
                info[attr] = getattr(pspec, attr)
            except Exception:
                pass
    if gtype.is_a(GObject.TYPE_ENUM):
        nicks = _enum_nicks(gtype)
        if nicks:
            info["choices"] = nicks
    if gtype.name == "GimpChoice":
        try:
            choice = Gimp.param_spec_choice_get_choice(pspec)
            info["choices"] = list(choice.list_choices())
        except Exception:
            pass
    return info


def _item_info(item, depth=0):
    ok, x, y = item.get_offsets()
    info = {
        "id": item.get_id(),
        "name": item.get_name(),
        "type": item.__gtype__.name,
        "visible": item.get_visible(),
        "width": item.get_width(),
        "height": item.get_height(),
        "x": x,
        "y": y,
        "locked": item.get_lock_content(),
    }
    if isinstance(item, Gimp.Layer):
        info["opacity"] = item.get_opacity()
        info["mode"] = item.get_mode().value_nick
        info["has_alpha"] = item.has_alpha()
        mask = item.get_mask()
        if mask is not None:
            info["mask_id"] = mask.get_id()
    if isinstance(item, Gimp.Drawable):
        try:
            info["type_desc"] = item.type().value_nick
        except Exception:
            pass
    if item.is_group() and depth < 12:
        info["children"] = [_item_info(child, depth + 1) for child in item.get_children()]
    return info


def _image_summary(image):
    gfile = image.get_file()
    return {
        "id": image.get_id(),
        "name": image.get_name(),
        "width": image.get_width(),
        "height": image.get_height(),
        "base_type": image.get_base_type().value_nick,
        "precision": image.get_precision().value_nick,
        "file": gfile.get_path() if gfile is not None else None,
        "dirty": image.is_dirty(),
        "layer_count": len(image.get_layers()),
    }


def _image_info(image):
    info = _image_summary(image)
    info["layers"] = [_item_info(layer) for layer in image.get_layers()]
    info["channels"] = [_item_info(ch) for ch in image.get_channels()]
    info["paths"] = [_item_info(p) for p in image.get_paths()]
    info["selected_layer_ids"] = [layer.get_id() for layer in image.get_selected_layers()]
    non_empty, x1, y1, x2, y2 = tuple(Gimp.Selection.bounds(image))[-5:]
    info["selection"] = {"non_empty": bool(non_empty), "x1": x1, "y1": y1, "x2": x2, "y2": y2}
    try:
        ok, xres, yres = image.get_resolution()
        info["resolution"] = [xres, yres]
    except Exception:
        pass
    return info


# --------------------------------------------------------------------------- coercion


def _get_image(image_id):
    if image_id is None:
        raise BridgeError("image_id is required")
    image = Gimp.Image.get_by_id(int(image_id))
    if image is None or not image.is_valid():
        raise BridgeError(f"no open image with id {image_id}")
    return image


def _get_item(item_id):
    if item_id is None:
        raise BridgeError("item id is required")
    item = Gimp.Item.get_by_id(int(item_id))
    if item is None or not item.is_valid():
        raise BridgeError(f"no item with id {item_id}")
    return item


def _make_color(value):
    if isinstance(value, Gegl.Color):
        return value
    try:
        r, g, b, a = core.parse_color(value)
    except ValueError:
        # Let GEGL try CSS names we do not know about.
        color = Gegl.Color.new(str(value))
        if color is None:
            raise
        return color
    color = Gegl.Color.new("black")
    color.set_rgba(r, g, b, a)
    return color


def _coerce_enum(value, gtype):
    members = _enum_members(gtype)
    if isinstance(value, bool):
        raise BridgeError(f"expected enum nick for {gtype.name}, got bool")
    if isinstance(value, int):
        for m in members:
            if int(m) == value:
                return m
        raise BridgeError(f"{value} is not a valid {gtype.name} value")
    nick = core.normalise_enum_nick(value)
    for m in members:
        if core.normalise_enum_nick(m.value_nick) == nick or core.normalise_enum_nick(m.value_name) == nick:
            return m
    for m in members:
        if core.normalise_enum_nick(m.value_name).endswith("-" + nick):
            return m
    raise BridgeError(f"{value!r} is not one of {[m.value_nick for m in members]} for {gtype.name}")


def _coerce(value, pspec):
    gtype = pspec.value_type
    name = gtype.name
    if name == "GimpImage":
        return _get_image(value["id"] if isinstance(value, dict) else value)
    if name in ITEM_TYPE_NAMES:
        return _get_item(value["id"] if isinstance(value, dict) else value)
    if name == "GimpCoreObjectArray":
        ids = value if isinstance(value, list) else [value]
        return [_get_item(v["id"] if isinstance(v, dict) else v) for v in ids]
    if name == "GeglColor":
        return _make_color(value)
    if name == "GFile":
        return Gio.File.new_for_path(os.path.abspath(os.path.expanduser(str(value))))
    if name == "GimpRunMode":
        return Gimp.RunMode.NONINTERACTIVE if value in (None, "", "noninteractive") else _coerce_enum(value, gtype)
    if gtype.is_a(GObject.TYPE_ENUM):
        return _coerce_enum(value, gtype)
    if name == "GStrv":
        return [str(v) for v in (value if isinstance(value, list) else [value])]
    if name == "gboolean":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if name in INT_TYPES:
        return int(value)
    if name in FLOAT_TYPES:
        return float(value)
    if name == "gchararray":
        return "" if value is None else str(value)
    if name == "GimpChoice":
        return str(value)
    return value


def _set_config_property(config, pspec, value):
    if pspec.value_type.name == "GimpCoreObjectArray":
        config.set_core_object_array(pspec.name, Gimp.Item, _coerce(value, pspec))
    else:
        config.set_property(pspec.name, _coerce(value, pspec))


# --------------------------------------------------------------------------- the bridge


class Bridge:
    def __init__(self, host, port, token, mode):
        self.host = host
        self.port = port
        self.token = token
        self.mode = mode
        self.loop = GLib.MainLoop()
        self.server_sock = None
        self.thread = None
        self.stopping = False
        Gegl.init(None)
        self.pdb = Gimp.get_pdb()
        self._proc_names = None
        self._filter_names = None
        self.ns = {}
        exec(
            "import gi\n"
            "gi.require_version('Gimp', '3.0'); gi.require_version('Gegl', '0.4'); gi.require_version('Babl', '0.1')\n"
            "from gi.repository import Gimp, Gegl, GLib, GObject, Gio, Babl\n"
            "import os, sys, math, json, time\n",
            self.ns,
        )
        self.ns["bridge"] = self
        self.ns["image_by_id"] = _get_image
        self.ns["item_by_id"] = _get_item
        self.ns["make_color"] = _make_color

    # -- lifecycle -----------------------------------------------------------------

    def start(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(4)
        self.server_sock.settimeout(0.5)
        self.thread = threading.Thread(target=self._accept_loop, name="gimp-agent-bridge", daemon=True)
        self.thread.start()

    def close(self):
        self.stopping = True
        if self.server_sock is not None:
            try:
                self.server_sock.close()
            except OSError:
                pass
            self.server_sock = None

    def _accept_loop(self):
        while not self.stopping:
            try:
                client, _addr = self.server_sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                self._serve_client(client)
            except Exception:
                traceback.print_exc()
            finally:
                try:
                    client.close()
                except OSError:
                    pass

    def _serve_client(self, client):
        client.settimeout(None)
        rfile = client.makefile("rb")
        wfile = client.makefile("wb")
        while not self.stopping:
            line = rfile.readline()
            if not line:
                return
            try:
                request = core.decode_message(line)
            except ValueError as exc:
                wfile.write(core.encode_message({"ok": False, "error": {"type": "BadRequest", "message": str(exc)}}))
                wfile.flush()
                continue
            response = self._handle_request(request)
            wfile.write(core.encode_message(response))
            wfile.flush()
            if request.get("op") == "shutdown" and response.get("ok"):
                return

    def _handle_request(self, request):
        req_id = request.get("id")
        if request.get("token") != self.token:
            return {"id": req_id, "ok": False, "error": {"type": "Unauthorized", "message": "bad or missing token"}}
        op = request.get("op")
        params = request.get("params") or {}
        if not isinstance(op, str) or not hasattr(self, "op_" + op):
            return {"id": req_id, "ok": False, "error": {"type": "UnknownOp", "message": f"unknown op {op!r}"}}
        result = self._run_on_main(getattr(self, "op_" + op), params)
        result["id"] = req_id
        return result

    def _run_on_main(self, func, params):
        done = threading.Event()
        box = {}

        def runner():
            try:
                box["r"] = {"ok": True, "result": func(params)}
            except Exception as exc:
                box["r"] = {
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()},
                }
            finally:
                done.set()
            return False

        GLib.idle_add(runner)
        done.wait()
        return box["r"]

    # -- helpers -------------------------------------------------------------------

    def _query_procedures(self, name_pattern):
        args = [name_pattern, "", "", "", "", "", ""]
        try:
            return list(self.pdb.query_procedures(*args))
        except TypeError:
            return list(self.pdb.query_procedures(*(args + [""])))

    def _all_proc_names(self):
        if self._proc_names is None:
            self._proc_names = sorted(self._query_procedures(".*"))
        return self._proc_names

    def _all_filter_names(self):
        if self._filter_names is None:
            self._filter_names = sorted(Gegl.list_operations())
        return self._filter_names

    def _lookup(self, name):
        proc = self.pdb.lookup_procedure(name)
        if proc is None:
            raise BridgeError(f"no PDB procedure named {name!r}")
        return proc

    def _maybe_display(self, image):
        if self.mode == "headless":
            return
        try:
            Gimp.Display.new(image)
        except Exception:
            pass

    def _flush(self):
        try:
            Gimp.displays_flush()
        except Exception:
            pass

    # -- ops -----------------------------------------------------------------------

    def op_ping(self, params):
        return {
            "bridge_version": core.BRIDGE_VERSION,
            "gimp_version": Gimp.version(),
            "python_version": sys.version.split()[0],
            "mode": self.mode,
            "pid": os.getpid(),
            "images": [_image_summary(img) for img in Gimp.get_images()],
            "config_dir": Gimp.directory(),
        }

    def op_shutdown(self, params):
        quit_gimp = bool(params.get("quit_gimp", self.mode == "headless"))
        GLib.timeout_add(150, self._do_shutdown, quit_gimp)
        return {"stopping": True, "quit_gimp": quit_gimp}

    def _do_shutdown(self, quit_gimp):
        self.close()
        self.loop.quit()
        # Headless launches quit GIMP from the batch code once this procedure returns, which keeps
        # the PDB return contract intact. A GUI session only quits when explicitly asked.
        if quit_gimp and self.mode == "gui":
            with contextlib.suppress(Exception):
                proc = self.pdb.lookup_procedure("gimp-quit")
                cfg = proc.create_config()
                cfg.set_property("force", True)
                GLib.timeout_add(200, lambda: (proc.run(cfg), False)[1])
        return False

    def op_exec(self, params):
        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise BridgeError("code must be a non-empty string")
        image = _get_image(params["image_id"]) if params.get("image_id") is not None else None
        out, err = io.StringIO(), io.StringIO()
        result = None
        if image is not None:
            image.undo_group_start()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    compiled = compile(code, "<agent>", "eval")
                except SyntaxError:
                    exec(compile(code, "<agent>", "exec"), self.ns)
                    result = self.ns.get("result")
                else:
                    result = eval(compiled, self.ns)
        finally:
            if image is not None:
                image.undo_group_end()
            self._flush()
        return {
            "stdout": core.truncate(out.getvalue()),
            "stderr": core.truncate(err.getvalue()),
            "result": _serialise(result) if result is not None else None,
        }

    def op_list_images(self, params):
        return [_image_summary(img) for img in Gimp.get_images()]

    def op_image_info(self, params):
        return _image_info(_get_image(params["image_id"]))

    def op_new_image(self, params):
        width = int(params.get("width", 512))
        height = int(params.get("height", 512))
        fill = str(params.get("fill", "transparent")).lower()
        image = Gimp.Image.new(width, height, Gimp.ImageBaseType.RGB)
        layer = Gimp.Layer.new(image, "Background", width, height, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
        if fill in ("transparent", "none"):
            layer.fill(Gimp.FillType.TRANSPARENT)
        elif fill in ("white", "background", "bg"):
            layer.fill(Gimp.FillType.WHITE if fill == "white" else Gimp.FillType.BACKGROUND)
        elif fill in ("foreground", "fg"):
            layer.fill(Gimp.FillType.FOREGROUND)
        else:
            Gimp.context_push()
            Gimp.context_set_foreground(_make_color(fill))
            layer.fill(Gimp.FillType.FOREGROUND)
            Gimp.context_pop()
        image.insert_layer(layer, None, 0)
        self._maybe_display(image)
        self._flush()
        return {"image": _image_summary(image), "layer_id": layer.get_id()}

    def op_open(self, params):
        path = os.path.abspath(os.path.expanduser(str(params["path"])))
        if not os.path.isfile(path):
            raise BridgeError(f"file not found: {path}")
        image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
        if image is None:
            raise BridgeError(f"GIMP could not load {path}")
        self._maybe_display(image)
        self._flush()
        return _image_info(image)

    def op_export(self, params):
        image = _get_image(params["image_id"])
        path = os.path.abspath(os.path.expanduser(str(params["path"])))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        ok = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(path), None)
        if not ok:
            raise BridgeError(f"export failed for {path}")
        return {"path": path, "bytes": os.path.getsize(path)}

    def op_close_image(self, params):
        image = _get_image(params["image_id"])
        image.delete()
        self._flush()
        return {"closed": int(params["image_id"])}

    def op_render(self, params):
        image = _get_image(params["image_id"]) if params.get("image_id") is not None else None
        if image is None:
            images = Gimp.get_images()
            if not images:
                raise BridgeError("no open images to render")
            image = images[0]
        max_size = int(params.get("max_size") or 1024)
        layer_id = params.get("layer_id")
        region = params.get("region")

        dup = image.duplicate()
        try:
            if layer_id is not None:
                wanted = int(layer_id)
                # Find the duplicate of the requested layer by position, then isolate it.
                src_items = _flatten_layers(image.get_layers())
                dup_items = _flatten_layers(dup.get_layers())
                for src, cpy in zip(src_items, dup_items, strict=False):
                    cpy.set_visible(src.get_id() == wanted)
            if region:
                x = int(region.get("x", 0))
                y = int(region.get("y", 0))
                w = int(region.get("width", dup.get_width() - x))
                h = int(region.get("height", dup.get_height() - y))
                dup.crop(w, h, x, y)
            visible = [layer for layer in dup.get_layers() if layer.get_visible()]
            if len(visible) > 1:
                dup.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
            w, h = dup.get_width(), dup.get_height()
            if max_size > 0 and max(w, h) > max_size:
                scale = max_size / float(max(w, h))
                dup.scale(max(1, int(round(w * scale))), max(1, int(round(h * scale))))
            fd, tmp = tempfile.mkstemp(prefix="gimp-agent-", suffix=".png")
            os.close(fd)
            try:
                ok = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, Gio.File.new_for_path(tmp), None)
                if not ok:
                    raise BridgeError("render export failed")
                with open(tmp, "rb") as fh:
                    data = fh.read()
            finally:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
            return {
                "png_base64": base64.b64encode(data).decode("ascii"),
                "width": dup.get_width(),
                "height": dup.get_height(),
                "source_width": image.get_width(),
                "source_height": image.get_height(),
                "image_id": image.get_id(),
            }
        finally:
            dup.delete()

    # PDB ------------------------------------------------------------------------

    def op_pdb_search(self, params):
        query = str(params.get("query") or "").strip().lower()
        limit = int(params.get("limit") or 25)
        names = self._all_proc_names()
        if query:
            terms = [t for t in query.replace("_", "-").split() if t]
            names = [n for n in names if all(t in n for t in terms)]
            if not names:
                names = [n for n in self._all_proc_names() if any(t in n for t in terms)]
        results = []
        for name in names[:limit]:
            proc = self.pdb.lookup_procedure(name)
            results.append(
                {
                    "name": name,
                    "blurb": proc.get_blurb() if proc else "",
                    "type": proc.get_proc_type().value_nick if proc else None,
                }
            )
        return {"total": len(names), "results": results}

    def op_pdb_describe(self, params):
        proc = self._lookup(str(params["name"]))
        return {
            "name": proc.get_name(),
            "blurb": proc.get_blurb() or "",
            "help": proc.get_help() or "",
            "type": proc.get_proc_type().value_nick,
            "menu_label": proc.get_menu_label() or None,
            "arguments": [_describe_pspec(p) for p in proc.get_arguments()],
            "return_values": [_describe_pspec(p) for p in proc.get_return_values()],
        }

    def op_pdb_call(self, params):
        proc = self._lookup(str(params["name"]))
        args = params.get("args") or {}
        if not isinstance(args, dict):
            raise BridgeError("args must be an object keyed by argument name")
        config = proc.create_config()
        pspecs = proc.get_arguments()
        names = [p.name for p in pspecs]
        by_name = {p.name: p for p in pspecs}
        unknown = [k for k in args if core.match_key(k, names) is None]
        if unknown:
            raise BridgeError(f"unknown argument(s) {unknown}; valid: {names}")
        if "run-mode" in by_name and core.match_key("run-mode", list(args)) is None:
            config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        for key, value in args.items():
            pspec = by_name[core.match_key(key, names)]
            _set_config_property(config, pspec, value)
        image = None
        image_key = core.match_key("image", list(args))
        if image_key is not None and bool(params.get("undo_group", True)):
            with contextlib.suppress(Exception):
                image = _get_image(args[image_key]["id"] if isinstance(args[image_key], dict) else args[image_key])
        if image is not None:
            image.undo_group_start()
        try:
            values = proc.run(config)
        finally:
            if image is not None:
                image.undo_group_end()
            self._flush()
        status = values.index(0)
        out = [_serialise(values.index(i)) for i in range(1, values.length())]
        if status != Gimp.PDBStatusType.SUCCESS:
            message = out[0] if out and isinstance(out[0], str) else ""
            raise BridgeError(f"{proc.get_name()} returned {status.value_nick}: {message}".strip())
        return {"status": status.value_nick, "values": out}

    # GEGL filters ---------------------------------------------------------------

    def op_filter_search(self, params):
        query = str(params.get("query") or "").strip().lower()
        limit = int(params.get("limit") or 25)
        names = self._all_filter_names()
        if query:
            terms = [t for t in query.replace("_", "-").split() if t]
            names = [n for n in names if all(t in n for t in terms)]
        results = []
        for name in names[:limit]:
            results.append(
                {
                    "op": name,
                    "title": Gegl.Operation.get_key(name, "title") or "",
                    "description": Gegl.Operation.get_key(name, "description") or "",
                    "categories": Gegl.Operation.get_key(name, "categories") or "",
                }
            )
        return {"total": len(names), "results": results}

    def op_filter_describe(self, params):
        op = str(params["op"])
        if op not in self._all_filter_names():
            raise BridgeError(f"unknown GEGL operation {op!r}")
        return {
            "op": op,
            "title": Gegl.Operation.get_key(op, "title") or "",
            "description": Gegl.Operation.get_key(op, "description") or "",
            "categories": Gegl.Operation.get_key(op, "categories") or "",
            "properties": [_describe_pspec(p) for p in Gegl.Operation.list_properties(op)],
        }

    def op_apply_filter(self, params):
        item = _get_item(params["layer_id"])
        if not isinstance(item, Gimp.Drawable):
            raise BridgeError("layer_id must reference a drawable (layer, mask or channel)")
        op = str(params["op"])
        if op not in self._all_filter_names():
            raise BridgeError(f"unknown GEGL operation {op!r}")
        mode = str(params.get("mode") or "merge").lower()
        props = params.get("params") or {}
        if not isinstance(props, dict):
            raise BridgeError("params must be an object of GEGL property values")
        image = item.get_image()
        image.undo_group_start()
        try:
            filt = Gimp.DrawableFilter.new(item, op, str(params.get("name") or op))
            config = filt.get_config()
            pspecs = [p for p in config.list_properties()]
            names = [p.name for p in pspecs]
            by_name = {p.name: p for p in pspecs}
            unknown = [k for k in props if core.match_key(k, names) is None]
            if unknown:
                raise BridgeError(f"unknown property(ies) {unknown} for {op}; valid: {names}")
            for key, value in props.items():
                pspec = by_name[core.match_key(key, names)]
                config.set_property(pspec.name, _coerce(value, pspec))
            if params.get("opacity") is not None:
                filt.set_opacity(float(params["opacity"]))
            if params.get("blend_mode"):
                filt.set_blend_mode(_coerce_enum(params["blend_mode"], Gimp.LayerMode.__gtype__))
            filt.update()
            if mode == "append":
                item.append_filter(filt)
            elif mode == "merge":
                item.merge_filter(filt)
            else:
                raise BridgeError("mode must be 'merge' or 'append'")
        finally:
            image.undo_group_end()
            self._flush()
        return {"applied": op, "mode": mode, "layer": _item_info(item)}

    def op_list_filters_on_layer(self, params):
        item = _get_item(params["layer_id"])
        if not isinstance(item, Gimp.Drawable):
            raise BridgeError("layer_id must reference a drawable")
        out = []
        for filt in item.get_filters():
            out.append(
                {
                    "id": filt.get_id(),
                    "name": filt.get_name(),
                    "op": filt.get_operation_name(),
                    "visible": filt.get_visible(),
                    "opacity": filt.get_opacity(),
                }
            )
        return out


def _flatten_layers(layers):
    out = []
    for layer in layers:
        out.append(layer)
        if layer.is_group():
            out.extend(_flatten_layers(layer.get_children()))
    return out


# --------------------------------------------------------------------------- plug-in entry


def _bridge_file_path():
    return os.path.join(Gimp.directory(), core.BRIDGE_FILE_NAME)


def run_bridge(procedure, config, data):
    try:
        return _run_bridge(procedure, config)
    except Exception as exc:
        traceback.print_exc()
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error.new_literal(GLib.quark_from_string("gimp-agent-bridge"), str(exc), 1)
        )


def _run_bridge(procedure, config):
    port = int(config.get_property("port") or 0) or int(os.environ.get("GIMP_AGENT_PORT") or core.DEFAULT_PORT)
    # The launcher sets GIMP_AGENT_MODE=headless for gimp-console runs; a menu start is always GUI.
    mode = "headless" if os.environ.get("GIMP_AGENT_MODE", "").lower() == "headless" else "gui"
    path = _bridge_file_path()
    token = os.environ.get("GIMP_AGENT_TOKEN") or core.load_or_create_token(path)

    bridge = Bridge(core.DEFAULT_HOST, port, token, mode)
    try:
        bridge.start()
    except OSError as exc:
        Gimp.message(f"GIMP Agent Bridge could not listen on {core.DEFAULT_HOST}:{port}: {exc}")
        raise

    core.write_bridge_file(path, port=port, token=token, pid=os.getpid(), gimp_version=Gimp.version(), mode=mode)
    if mode == "gui":
        Gimp.message(f"GIMP Agent Bridge listening on {core.DEFAULT_HOST}:{port}")
    print(f"[gimp-agent-bridge] listening on {core.DEFAULT_HOST}:{port} ({mode})", file=sys.stderr)

    try:
        bridge.loop.run()
    finally:
        bridge.close()
        with contextlib.suppress(OSError):
            os.remove(path)
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class GimpAgentBridgePlugIn(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [core.PROCEDURE_NAME]

    def do_create_procedure(self, name):
        procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_bridge, None)
        procedure.set_menu_label("Start Agent Bridge")
        procedure.add_menu_path("<Image>/Filters/Development/")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)
        procedure.set_documentation(
            "Start the GIMP Agent Bridge for gimp-agent-mcp",
            "Listens on 127.0.0.1 and executes agent requests inside GIMP. Blocks until shutdown.",
            name,
        )
        procedure.set_attribution("gimp-agent-mcp contributors", "Apache-2.0", "2026")
        procedure.add_enum_argument(
            "run-mode", "Run mode", "The run mode", Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE, GObject.ParamFlags.READWRITE
        )
        procedure.add_int_argument(
            "port", "Port", "TCP port on 127.0.0.1 (0 = default)", 0, 65535, 0, GObject.ParamFlags.READWRITE
        )
        return procedure


Gimp.main(GimpAgentBridgePlugIn.__gtype__, sys.argv)
