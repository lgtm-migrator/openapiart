"""Abstract plugin class
"""
import jsonpath_ng


class OpenApiArtPlugin(object):
    """Abstract class for creating a plugin generator"""

    def __init__(self, **kwargs):
        self._fp = None
        self._openapi = None
        self._license = kwargs["license"]
        self._info = kwargs["info"]
        self._output_dir = kwargs["output_dir"]
        self._python_module_name = (
            None
            if "python_module_name" not in kwargs
            else kwargs["python_module_name"]
        )
        self._protobuf_package_name = kwargs["protobuf_package_name"]
        self._protobuf_file_name = kwargs["protobuf_package_name"]
        self._go_sdk_package_dir = kwargs["go_sdk_package_dir"]
        self._go_sdk_package_name = (
            None
            if "go_sdk_package_name" not in kwargs
            else kwargs["go_sdk_package_name"]
        )
        self.default_indent = "    "
        self._parsers = {}

    def _init_fp(self, filename):
        self._filename = filename
        self._fp = open(self._filename, "wb")

    def _close_fp(self):
        self._fp.close()

    def _write(self, line="", indent=0, newline=True):
        line = "{}{}{}".format(
            self.default_indent * indent, line, "\n" if newline else ""
        )
        self._fp.write(line.encode())

    def _get_parser(self, pattern):
        if pattern not in self._parsers:
            parser = jsonpath_ng.parse(pattern)
            self._parsers[pattern] = parser
        else:
            parser = self._parsers[pattern]
        return parser

    def _get_camel_case(self, value):
        camel_case = ""
        for piece in value.split("_"):
            camel_case += piece[0].upper()
            if len(piece) > 1:
                camel_case += piece[1:]
        return camel_case

    def _justify_desc(self, text, indent=0, use_multi=False):
        indent = " " * (indent * 2)
        lines = []
        text = text.split("\n")
        for line in text:
            char_80 = ""
            for word in line.split(" "):
                if len(char_80) <= 80:
                    char_80 += word + " "
                    continue
                lines.append(char_80.strip())
                char_80 = word + " "
            if char_80 != "":
                lines.append(char_80.strip())
            # lines.append("\n{}{}".format(indent, comment).join(each_line))
        if use_multi is True:
            return (
                "{}/* ".format(indent)
                + "\n{} * ".format(indent).join(lines)
                + " */"
            )
        return "{}// ".format(indent) + "\n{}// ".format(indent).join(lines)

    def _resolve_response(self, parser_result):
        """returns the inner response type if any"""
        if "/components/responses" in parser_result[0].value:
            jsonpath = "$.{}..schema".format(
                parser_result[0].value[2:].replace("/", ".")
            )
            schema = self._get_parser(jsonpath).find(self._openapi)[0].value
            response_component_ref = self._get_parser("$..'$ref'").find(schema)
            return response_component_ref
        return parser_result

    def _get_schema_object_name_from_ref(self, ref):
        final_piece = ref.split("/")[-1]
        return final_piece.replace(".", "")