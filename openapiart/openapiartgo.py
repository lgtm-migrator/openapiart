from .openapiartplugin import OpenApiArtPlugin
import os
import subprocess
import shutil


class FluentStructure(object):
    def __init__(self):
        self.internal_struct_name = None
        self.external_interface_name = None
        self.external_new_methods = []
        self.external_rpc_methods = []
        self.internal_http_methods = []
        self.components = {}


class FluentRpc(object):
    """SetConfig(config Config) error"""

    def __init__(self):
        self.operation_name = None
        self.method = None
        self.request = "emptypb.Empty{}"
        self.responses = []
        self.http_call = None


class FluentRpcResponse(object):
    """<operation_name>StatusCode<status_code>
    status_code is the http status code
    fluent_new is the 2xx response, all other status codes this should be None
    """

    def __init__(self):
        self.status_code = None
        self.schema = None
        self.request_return_type = None


class FluentHttp(object):
    """httpSetConfig(config Config) error"""

    def __init__(self):
        self.operation_name = None
        self.method = None
        self.request = None
        self.request_return_type = None
        self.responses = []


class FluentNew(object):
    """New<external_interface_name> <external_interface_name>"""

    def __init__(self):
        self.generated = False
        self.interface = None
        self.struct = None
        self.method = None
        self.schema_name = None
        self.schema_object = None
        self.isRpcResponse = False
        self.interface_fields = []

    def isOptional(self, property_name):
        if self.schema_object is None:
            return True
        if "required" not in self.schema_object:
            return True
        if property_name not in self.schema_object["required"]:
            return True
        return False


class FluentField(object):
    def __init__(self):
        self.name = None
        self.description = None
        self.type = None
        self.isOptional = True
        self.isPointer = True
        self.isArray = False
        self.struct = None
        self.external_struct = None
        self.setter_method = None
        self.getter_method = None
        self.adder_method = None
        self.has_method = None


class OpenApiArtGo(OpenApiArtPlugin):
    """Generates a fluent interface go package that encapsulates protoc
    generated .pg.go and _grpc.pb.go content

    Toolchain
    ---------
    api/**.yaml | OpenAPIArt.bundler
    out: openapi.yaml | openapiartprotobuf
    out: sanity.proto | protoc
    out: sanity.pb.go, sanity_grpc.pb.go | openapiartgo (fluent wrapper around pb.go, _grpc.pb.go)
    output: currently handwritten poc.go (want generated sanity.go)

    - Update the openartprotobuf.py to generate grpc-gateway stubs
        import "google/api/annotations.proto";

        rpc SetConfig(SetConfigRequest) SetConfigResponse {
            option (google.api.http) = {
                post: "/config",
                body: "*"
            };
        }

    - Generate the .proto file using artifacts.py

    - From the .proto generate the .pb.go and _grpc.pb.go
        protoc --go_out=. --go-grpc_out=. --grpc-gateway_out=. --experimental_allow_proto3_optional .proto

    - From the bundled openapi.yaml generate a custom fluent interface using
    openapiartgo.py that encapsulates the generated .pb.go and _grpc.pb.go
        - features:
            - top level api, api interface
            - api transport (grpc, http) ->
            - path item object operationId -> api interface member
            - path item object input schema -> part of api interface, internal struct, external interface
            - all components/schemas internal struct, external interface


    Contents should be <pkgname>.go, go.mod, go.sum under a specific directory

    Workflow/action should install go
        - https://github.com/actions/setup-go
    Which needs to copy the generated go file to the test dir
    The action then needs to run the go test to ensure all tests pass
    """

    def __init__(self, **kwargs):
        super(OpenApiArtGo, self).__init__(**kwargs)
        self._api = FluentStructure()
        self._api_interface_methods = []
        self._oapi_go_types = {
            "string": "string",
            "boolean": "bool",
            "integer": "int32",
            "number": "float32",
            "numberfloat": "float32",
            "numberdouble": "float64",
            # "stringmac": "StringMac",
            # "stringipv4": "StringIpv4",
            # "stringipv6": "StringIpv6",
            # "stringhex": "StringHex",
            "stringbinary": "[]byte",
        }

    def generate(self, openapi):
        self._openapi = openapi
        self._ux_path = os.path.normpath(os.path.join(self._output_dir, "..", os.path.split(self._go_sdk_package_dir)[-1]))
        self._protoc_path = os.path.normpath(os.path.join(self._ux_path, self._protobuf_package_name))
        self._structs = {}
        self._write_mod_file()
        self._write_go_file()
        self._format_go_file()
        self._tidy_mod_file()

    def _write_mod_file(self):
        self._filename = os.path.normpath(os.path.join(self._ux_path, "go.mod"))
        self.default_indent = "    "
        self._init_fp(self._filename)
        self._write("module {}".format(self._go_sdk_package_dir))
        self._write()
        self._write("go 1.16")
        self._close_fp()

    def _write_go_file(self):
        self._filename = os.path.normpath(os.path.join(self._ux_path, "{}.go".format(self._go_sdk_package_name)))
        self.default_indent = "    "
        self._init_fp(self._filename)
        self._write_package_docstring(self._openapi["info"])
        self._write_package()
        self._write_common_code()
        self._write_types()
        self._build_api_interface()
        self._build_request_interfaces()
        self._write_component_interfaces()
        self._close_fp()

    def _write_package_docstring(self, info_object):
        """Write the header of the generated go code file which consists of:
        - license, version and description
        - package name
        - common custom code
        """
        self._write("// {}".format(self._info))
        for line in self._license.split("\n"):
            self._write("// {}".format(line))
        self._write()

    def _write_package(self):
        self._write("package {go_sdk_package_name}".format(go_sdk_package_name=self._go_sdk_package_name))
        self._write()

    def _write_common_code(self):
        """Writes the base wrapper go code"""
        line = 'import {pb_pkg_name} "{go_sdk_pkg_dir}/{pb_pkg_name}"'.format(pb_pkg_name=self._protobuf_package_name, go_sdk_pkg_dir=self._go_sdk_package_dir)
        self._write(line)
        self._write('import "google.golang.org/protobuf/types/known/emptypb"')
        self._write('import "google.golang.org/grpc"')
        self._write('import "github.com/ghodss/yaml"')
        self._write('import "google.golang.org/protobuf/encoding/protojson"')
        self._write('import "github.com/golang/protobuf/proto"')
        with open(os.path.join(os.path.dirname(__file__), "common.go")) as fp:
            self._write(fp.read().strip().strip("\n"))
        self._write()

    def _write_types(self):
        for _, go_type in self._oapi_go_types.items():
            if go_type.startswith("String"):
                self._write("type {go_type} string".format(go_type=go_type))
        self._write()

    def _get_internal_name(self, openapi_name):
        name = self._get_external_struct_name(openapi_name)
        name = name[0].lower() + name[1:]
        if name in ["error"]:
            name = "_" + name
        return name

    def _get_external_field_name(self, openapi_name):
        external_name = ""
        for piece in openapi_name.replace(".", "").split("_"):
            for i in range(len(piece)):
                if i == 0 and piece[i].isdigit() is False:
                    external_name += piece[i].upper()
                elif piece[i].isdigit():
                    if "_" + piece[i] in openapi_name:
                        external_name += "_" + piece[i]
                    else:
                        external_name += piece[i]
                elif external_name[-1].isdigit():
                    external_name += piece[i].upper()
                else:
                    external_name += piece[i]
        if external_name in ["String"]:
            external_name += "_"
        return external_name

    def _get_external_struct_name(self, openapi_name):
        return self._get_external_field_name(openapi_name).replace("_", "")

    def _resolve_response(self, parser_result):
        """returns the inner response type if any"""
        if "/components/responses" in parser_result[0].value:
            jsonpath = "$.{}..schema".format(parser_result[0].value[2:].replace("/", "."))
            schema = self._get_parser(jsonpath).find(self._openapi)[0].value
            response_component_ref = self._get_parser("$..'$ref'").find(schema)
            return response_component_ref
        return parser_result

    def _build_api_interface(self):
        self._api.internal_struct_name = """{internal_name}Api""".format(internal_name=self._get_internal_name(self._go_sdk_package_name))
        self._api.external_interface_name = """{external_name}Api""".format(external_name=self._get_external_struct_name(self._go_sdk_package_name))
        for url, path_object in self._openapi["paths"].items():
            for operation_id in self._get_parser("$..operationId").find(path_object):
                path_item_object = operation_id.context.value
                rpc = FluentRpc()
                http = FluentHttp()
                rpc.operation_name = self._get_external_struct_name(operation_id.value)
                http.operation_name = self._get_external_struct_name(operation_id.value)
                if len([m for m in self._api.external_rpc_methods if m.operation_name == rpc.operation_name]) == 0:
                    self._api.external_rpc_methods.append(rpc)
                if len([m for m in self._api.internal_http_methods if m.operation_name == http.operation_name]) == 0:
                    self._api.internal_http_methods.append(http)
                rpc.request_return_type = "{operation_response_name}Response_StatusCode200".format(
                    operation_response_name=self._get_external_struct_name(rpc.operation_name),
                )
                binary_type = self._get_parser("$..responses..'200'..schema..format").find(path_item_object)
                ref_type = self._get_parser("$..responses..'200'..'$ref'").find(path_item_object)
                if len(binary_type) == 1:
                    rpc.request_return_type = "[]byte"
                elif len(ref_type) == 1:
                    request_return_type = self._get_schema_object_name_from_ref(self._resolve_response(ref_type)[0].value)
                    rpc.request_return_type = self._get_external_struct_name(request_return_type)

                http.request_return_type = rpc.request_return_type
                ref = self._get_parser("$..requestBody..'$ref'").find(path_item_object)
                if len(ref) == 1:
                    new = FluentNew()
                    new.schema_name = self._get_schema_object_name_from_ref(ref[0].value)
                    new.schema_object = self._get_schema_object_from_ref(ref[0].value)
                    new.interface = self._get_external_struct_name(new.schema_name)
                    new.struct = self._get_internal_name(new.schema_name)
                    new.method = """New{interface}() {interface}""".format(interface=new.interface)
                    if len([m for m in self._api.external_new_methods if m.schema_name == new.schema_name]) == 0:
                        self._api.external_new_methods.append(new)
                    rpc.request = "{pb_pkg_name}.{operation_name}Request{{{interface}: {struct}.msg()}}".format(
                        pb_pkg_name=self._protobuf_package_name,
                        operation_name=rpc.operation_name,
                        interface=new.interface,
                        struct=new.struct,
                    )
                    rpc.method = """{operation_name}({struct} {interface}) ({request_return_type}, error)""".format(
                        operation_name=rpc.operation_name,
                        operation_response_name=self._get_external_struct_name(rpc.operation_name),
                        struct=new.struct,
                        interface=new.interface,
                        request_return_type=rpc.request_return_type,
                    )
                    rpc.http_call = """return api.http{operation_name}({struct})""".format(
                        operation_name=rpc.operation_name,
                        struct=new.struct,
                    )
                    if url.startswith("/"):
                        url = url[1:]
                    http.request = """api.httpSendRecv("{url}", {struct}.ToJson(), "{method}")""".format(
                        operation_name=http.operation_name, url=url, struct=new.struct, method=str(operation_id.context.path.fields[0]).upper()
                    )
                    http.method = """http{rpc_method}""".format(rpc_method=rpc.method)
                else:
                    rpc.method = """{operation_name}() ({request_return_type}, error)""".format(
                        operation_name=rpc.operation_name,
                        operation_response_name=self._get_external_struct_name(rpc.operation_name),
                        request_return_type=rpc.request_return_type,
                    )
                    rpc.http_call = """return api.http{operation_name}()""".format(
                        operation_name=rpc.operation_name,
                    )
                    http.request = """api.httpSendRecv("{url}", "", "{method}")""".format(url=url, method=str(operation_id.context.path.fields[0]).upper())
                    http.method = """http{rpc_method}""".format(rpc_method=rpc.method)
                for ref in self._get_parser("$..responses").find(path_item_object):
                    for status_code, response_object in ref.value.items():
                        response = FluentRpcResponse()
                        response.status_code = status_code
                        response.request_return_type = """New{operation_name}Response""".format(
                            operation_name=rpc.operation_name,
                        )
                        ref = self._get_parser("$..'$ref'").find(response_object)
                        if len(ref) > 0:
                            response.schema = {"$ref": self._resolve_response(ref)[0].value}
                        else:
                            response.schema = self._get_parser("$..schema").find(response_object)[0].value
                        rpc.responses.append(response)
                        http.responses.append(response)

        self._build_response_interfaces()

        # write the go code
        self._write(
            """type {internal_struct_name} struct {{
                api
                grpcClient {pb_pkg_name}.OpenapiClient
                httpClient httpClient
            }}

            // grpcConnect builds up a grpc connection
            func (api *{internal_struct_name}) grpcConnect() error {{
                if api.grpcClient == nil {{
                    conn, err := grpc.Dial(api.grpc.location, grpc.WithInsecure())
                    if err != nil {{
                        return err
                    }}
                    api.grpcClient = {pb_pkg_name}.NewOpenapiClient(conn)
                }}
                return nil
            }}

            // NewApi returns a new instance of the top level interface hierarchy
            func NewApi() {interface} {{
                api := {internal_struct_name}{{}}
                return &api
            }}
            
            // httpConnect builds up a http connection
            func (api *{internal_struct_name}) httpConnect() error {{
                if api.httpClient.client == nil {{
                    var verify = !api.http.verify
                    client := httpClient{{
                        client: &http.Client{{
                            Transport: &http.Transport{{
                                TLSClientConfig: &tls.Config{{InsecureSkipVerify: verify}},
                            }},
                        }},
                        ctx: context.Background(),
                    }}
                    api.httpClient = client
                }}
                return nil
            }}
            
            func (api *{internal_struct_name}) httpSendRecv(urlPath string, jsonBody string, method string) (*http.Response, error) {{
                err := api.httpConnect()
                if err != nil {{
                    return nil, err
                }}
                httpClient := api.httpClient
                var bodyReader = bytes.NewReader([]byte(jsonBody))
                queryUrl, err := url.Parse(api.http.location)
                if err != nil {{
                    return nil, err
                }}
                basePath := fmt.Sprintf(urlPath)
                queryUrl, _ = queryUrl.Parse(basePath)
                req, _ := http.NewRequest(method, queryUrl.String(), bodyReader)
                req.Header.Set("Content-Type", "application/json")
                req = req.WithContext(httpClient.ctx)
                return httpClient.client.Do(req)
            }}            
            """.format(
                internal_struct_name=self._api.internal_struct_name,
                interface=self._api.external_interface_name,
                pb_pkg_name=self._protobuf_package_name,
            )
        )
        methods = []
        for new in self._api.external_new_methods:
            methods.append(new.method)
        for rpc in self._api.external_rpc_methods:
            methods.append(rpc.method)
        method_signatures = "\n".join(methods)
        self._write(
            """type {external_interface_name} interface {{
                Api
                {method_signatures}
            }}
            """.format(
                external_interface_name=self._api.external_interface_name,
                method_signatures=method_signatures,
            )
        )
        for new in self._api.external_new_methods:
            self._write(
                """func (api *{internal_struct_name}) {method} {{
                    return &{struct}{{obj: &{pb_pkg_name}.{interface}{{}}}}
                }}
                """.format(
                    internal_struct_name=self._api.internal_struct_name,
                    method=new.method,
                    struct=new.struct,
                    pb_pkg_name=self._protobuf_package_name,
                    interface=new.interface,
                )
            )
        for rpc in self._api.external_rpc_methods:
            error_handling = ""
            for response in rpc.responses:
                if response.status_code.startswith("2"):
                    continue
                error_handling += """if resp.GetStatusCode_{status_code}() != nil {{
                        data, _ := yaml.Marshal(resp.GetStatusCode_{status_code}())
                        return nil, fmt.Errorf(string(data))
                    }}
                    """.format(
                    status_code=response.status_code,
                )
            error_handling += 'return nil, fmt.Errorf("response not implemented")'
            if rpc.request_return_type == "[]byte":
                return_value = "resp.GetStatusCode_200()"
            else:
                return_value = "&{struct}{{obj: resp.GetStatusCode_200()}}".format(
                    struct=self._get_internal_name(rpc.request_return_type),
                    request_return_type=rpc.request_return_type,
                )
            self._write(
                """func (api *{internal_struct_name}) {method} {{
                    if api.hasHttpTransport() {{
                            {http_call}
                    }}
                    
                    if err := api.grpcConnect(); err != nil {{
                        return nil, err
                    }}
                    request := {request}
                    ctx, cancelFunc := context.WithTimeout(context.Background(), api.grpc.requestTimeout)
                    defer cancelFunc()
                    resp, err := api.grpcClient.{operation_name}(ctx, &request)
                    if err != nil {{
                        return nil, err
                    }}
                    if resp.GetStatusCode_200() != nil {{
                        return {return_value}, nil
                    }}
                    {error_handling}
                }}
                """.format(
                    internal_struct_name=self._api.internal_struct_name,
                    method=rpc.method,
                    request=rpc.request,
                    operation_name=rpc.operation_name,
                    operation_response_name=self._get_internal_name(rpc.operation_name),
                    error_handling=error_handling,
                    return_value=return_value,
                    http_call=rpc.http_call,
                )
            )

        for http in self._api.internal_http_methods:
            error_handling = ""
            success_method = None
            for response in http.responses:
                if response.status_code.startswith("2"):
                    success_method = response.request_return_type
                else:
                    error_handling += """if resp.StatusCode == {status_code} {{
                            return nil, fmt.Errorf(string(bodyBytes))
                        }}
                        """.format(
                        status_code=response.status_code,
                    )
            error_handling += 'return nil, fmt.Errorf("response not implemented")'
            if http.request_return_type == "[]byte":
                success_handling = """return bodyBytes, nil""".format(package_name=self._protobuf_package_name, operation_name=http.operation_name)
            else:
                success_handling = """obj := api.{success_method}()
                    if err := obj.StatusCode200().FromJson(string(bodyBytes)); err != nil {{
                        return nil, err
                    }}
                    return obj.StatusCode200(), nil""".format(
                    success_method=success_method,
                    pb_pkg_name=self._protobuf_package_name,
                )
            self._write(
                """func (api *{internal_struct_name}) {method} {{
                    resp, err := {request}
                    if err != nil {{
                        return nil, err
                    }}
                    bodyBytes, err := ioutil.ReadAll(resp.Body)
                    defer resp.Body.Close()
                    if err != nil {{
                        return nil, err
                    }}
                    if resp.StatusCode == 200 {{
                        {success_handling}
                    }}
                    {error_handling}
                }}
                """.format(
                    internal_struct_name=self._api.internal_struct_name,
                    method=http.method,
                    request=http.request,
                    success_handling=success_handling,
                    error_handling=error_handling,
                )
            )

    def _build_request_interfaces(self):
        for new in self._api.external_new_methods:
            self._write_interface(new)

    def _write_component_interfaces(self):
        while True:
            components = [component for _, component in self._api.components.items() if component.generated is False]
            if len(components) == 0:
                break
            for component in components:
                self._write_interface(component)

    def _build_response_interfaces(self):
        for rpc in self._api.external_rpc_methods:
            new = FluentNew()
            new.schema_object = {
                "type": "object",
                "properties": {},
            }
            properties = {}
            for response in rpc.responses:
                properties["status_code_{}".format(response.status_code)] = response.schema
            new.schema_object["properties"] = properties
            new.struct = "{operation_name}Response".format(
                operation_name=self._get_internal_name(rpc.operation_name),
            )
            new.interface = "{operation_name}Response".format(
                operation_name=rpc.operation_name,
            )
            new.method = "New{interface}() {interface}".format(
                interface=new.interface,
            )
            new.schema_name = self._get_external_struct_name(new.interface)
            # new.isRpcResponse = True
            self._api.external_new_methods.append(new)

    def _write_interface(self, new):
        if new.schema_name in self._api.components:
            new = self._api.components[new.schema_name]
        else:
            self._api.components[new.schema_name] = new
        if new.generated is True:
            return
        else:
            new.generated = True
        self._write(
            """type {struct} struct {{
                obj *{pb_pkg_name}.{interface}
            }}
            
            func (obj *{struct}) msg() *{pb_pkg_name}.{interface} {{
                return obj.obj
            }}

            func (obj *{struct}) ToPbText() string {{
                return proto.MarshalTextString(obj.msg())
            }}

            func (obj *{struct}) FromPbText(value string) error {{
                return proto.UnmarshalText(value, obj.msg())
            }}

            func (obj *{struct}) ToYaml() string {{
                opts := protojson.MarshalOptions{{
                    UseProtoNames:   true,
                    AllowPartial:    true,
                    EmitUnpopulated: false,
                }}
                data, err := opts.Marshal(obj.msg())
                data, err = yaml.JSONToYAML(data)
                if err != nil {{
                    panic(err)
                }}
                return string(data)
            }}

            func (obj *{struct}) FromYaml(value string) error {{
                data, err := yaml.YAMLToJSON([]byte(value))
                if err != nil {{
                    return err
                }}
                opts := protojson.UnmarshalOptions{{
                    AllowPartial: true,
                    DiscardUnknown: false,
                }}
                return opts.Unmarshal([]byte(data), obj.msg())
            }}

            func (obj *{struct}) ToJson() string {{
                opts := protojson.MarshalOptions{{
                    UseProtoNames:   true,
                    AllowPartial:    true,
                    EmitUnpopulated: false,
                    Indent:          "  ",
                }}
                data, err := opts.Marshal(obj.msg())
                if err != nil {{
                    panic(err)
                }}
                return string(data)
            }}

            func (obj *{struct}) FromJson(value string) error {{
                opts := protojson.UnmarshalOptions{{
                    AllowPartial: true,
                    DiscardUnknown: false,
                }}
                return opts.Unmarshal([]byte(value), obj.msg())
            }}
        """.format(
                struct=new.struct,
                pb_pkg_name=self._protobuf_package_name,
                interface=new.interface,
            )
        )
        self._build_setters_getters(new)
        interfaces = [
            "ToPbText() string",
            "ToYaml() string",
            "ToJson() string",
            "FromPbText(value string) error",
            "FromYaml(value string) error",
            "FromJson(value string) error",
        ]
        for field in new.interface_fields:
            interfaces.append(field.getter_method)
            if field.setter_method is not None:
                interfaces.append(field.setter_method)
            if field.has_method is not None:
                interfaces.append(field.has_method)
        interface_signatures = "\n".join(interfaces)
        self._write(
            """type {interface} interface {{
                msg() *{pb_pkg_name}.{interface}
                {interface_signatures}
            }}
        """.format(
                interface=new.interface,
                pb_pkg_name=self._protobuf_package_name,
                interface_signatures=interface_signatures,
            )
        )
        for field in new.interface_fields:
            self._write_field_getter(new, field)
            self._write_field_has(new, field)
            self._write_field_setter(new, field)
            self._write_field_adder(new, field)

    def _write_field_getter(self, new, field):
        if field.getter_method is None:
            return
        elif field.isArray and field.isEnum is False:
            if field.struct:
                body = """if obj.obj.{name} == nil {{
                        obj.obj.{name} = []*{pb_pkg_name}.{pb_struct}{{}}
                    }}
                    return &{parent}{interface}Iter{{obj: obj}}""".format(
                    name=field.name,
                    pb_pkg_name=self._protobuf_package_name,
                    pb_struct=field.external_struct,
                    interface=field.external_struct,
                    parent=new.struct,
                )
            else:
                body = """if obj.obj.{name} == nil {{
                        obj.obj.{name} = make({type}, 0)
                    }}
                    return obj.obj.{name}""".format(
                    name=field.name,
                    type=field.type,
                )
        elif field.struct is not None:
            # at this time proto generation ignores the optional keyword
            # if the type is an object
            set_choice = ""
            if field.setChoiceValue is not None:
                set_choice = """obj.SetChoice({interface}Choice.{enum})""".format(
                    interface=new.interface,
                    enum=field.setChoiceValue,
                )
            body = """if obj.obj.{name} == nil {{
                    obj.obj.{name} = &{pb_pkg_name}.{pb_struct}{{}}
                }}
                {set_choice}
                return &{struct}{{obj: obj.obj.{name}}}""".format(
                name=field.name,
                pb_pkg_name=self._protobuf_package_name,
                pb_struct=field.external_struct,
                struct=field.struct,
                set_choice=set_choice,
            )
        elif field.isEnum:
            enum_types = []
            for enum in field.enums:
                enum_types.append(
                    "{enumupper} {interface}{fieldname}Enum".format(
                        enumupper=enum.upper(),
                        interface=new.interface,
                        fieldname=field.name,
                    )
                )
            enum_values = []
            for enum in field.enums:
                enum_values.append(
                    '{enumupper}: {interface}{fieldname}Enum("{enum}")'.format(
                        enumupper=enum.upper(),
                        interface=new.interface,
                        fieldname=field.name,
                        enum=enum,
                    )
                )
            self._write(
                """type {interface}{fieldname}Enum string

                var {interface}{fieldname} = struct {{
                    {enum_types}
                }} {{
                    {enum_values},
                }}
                """.format(
                    interface=new.interface,
                    fieldname=field.name,
                    enum_types="\n".join(enum_types),
                    enum_values=",\n".join(enum_values),
                )
            )
            if field.isArray:
                self._write(
                    """func (obj *{struct}) {fieldname}() []{interface}{fieldname}Enum {{
                        items := []{interface}{fieldname}Enum{{}}
                        for _, item := range obj.obj.{fieldname} {{
                            items = append(items, {interface}{fieldname}Enum(item.String()))
                        }}
                    return items
                }}
                """.format(
                        struct=new.struct,
                        interface=new.interface,
                        fieldname=field.name,
                    )
                )
            else:
                self._write(
                    """func (obj *{struct}) {fieldname}() {interface}{fieldname}Enum {{
                    return {interface}{fieldname}Enum(obj.obj.{fieldname}.Enum().String())
                }}
                """.format(
                        struct=new.struct,
                        interface=new.interface,
                        fieldname=field.name,
                    )
                )
            return
        elif field.isPointer:
            body = """return *obj.obj.{fieldname}""".format(
                fieldname=field.name,
            )
        else:
            body = """return obj.obj.{fieldname}""".format(
                fieldname=field.name,
            )
        self._write(
            """
            // {fieldname} returns a {fieldtype}\n{description}
            func (obj *{struct}) {getter_method} {{
                {body}
            }}
            """.format(
                fieldname=self._get_external_struct_name(field.name),
                struct=new.struct,
                getter_method=field.getter_method,
                body=body,
                description=field.description,
                fieldtype=field.type,
            )
        )

    def _write_field_setter(self, new, field):
        if field.setter_method is None:
            return
        if field.isArray and field.isEnum:
            body = """items := []{pb_pkg_name}.{interface}_{fieldname}_Enum{{}}
                for _, item:= range value {{
                    intValue := {pb_pkg_name}.{interface}_{fieldname}_Enum_value[string(item)]
                    items = append(items, {pb_pkg_name}.{interface}_{fieldname}_Enum(intValue))
                }}
                obj.obj.{fieldname} = items""".format(
                interface=new.interface,
                struct=new.struct,
                fieldname=field.name,
                pb_pkg_name=self._protobuf_package_name,
            )
        elif field.isArray:
            body = """if obj.obj.{fieldname} == nil {{
                    obj.obj.{fieldname} = make({fieldtype}, 0)
                }}
                for _, item := range value {{
                    obj.obj.{fieldname} = append(obj.obj.{fieldname}, item)
                }}""".format(
                fieldname=field.name,
                fieldtype=field.type,
            )
        elif field.isEnum:
            if field.isPointer:
                body = """enumValue := {pb_pkg_name}.{interface}_{fieldname}_Enum(intValue)
                obj.obj.{fieldname} = &enumValue""".format(
                    pb_pkg_name=self._protobuf_package_name,
                    interface=new.interface,
                    fieldname=field.name,
                )
            else:
                body = """obj.obj.{fieldname} = {pb_pkg_name}.{interface}_{fieldname}_Enum(intValue)""".format(
                    pb_pkg_name=self._protobuf_package_name,
                    interface=new.interface,
                    fieldname=field.name,
                )
            self._write(
                """func (obj* {struct}) Set{fieldname}(value {interface}{fieldname}Enum) {interface} {{
                intValue := {pb_pkg_name}.{interface}_{fieldname}_Enum_value[string(value)]
                {body}
                return obj
            }}
            """.format(
                    pb_pkg_name=self._protobuf_package_name,
                    interface=new.interface,
                    struct=new.struct,
                    fieldname=field.name,
                    body=body,
                )
            )
            return
        elif field.isPointer:
            body = """obj.obj.{fieldname} = &value""".format(fieldname=field.name)
        else:
            body = """obj.obj.{fieldname} = value""".format(fieldname=field.name)
        set_choice = ""
        if field.setChoiceValue is not None:
            set_choice = """obj.SetChoice({interface}Choice.{enum})""".format(
                interface=new.interface,
                enum=field.setChoiceValue,
            )
        self._write(
            """
            // Set{fieldname} sets the {fieldtype} value in the {fieldstruct} object\n{description}
            func (obj *{newstruct}) {setter_method} {{
                {body}
                {set_choice}
                return obj
            }}
            """.format(
                fieldname=self._get_external_struct_name(field.name),
                newstruct=new.struct,
                setter_method=field.setter_method,
                body=body,
                description=field.description,
                fieldtype=field.type,
                fieldstruct=new.interface,
                set_choice=set_choice,
            )
        )

    def _write_field_adder(self, new, field):
        if field.adder_method is None:
            return
        interface_name = new.interface + field.external_struct + "Iter"
        if interface_name in self._api.components:
            return
        new_iter = FluentNew()
        new_iter.schema_name = interface_name
        new_iter.interface = interface_name
        new_iter.internal_struct = interface_name[0].lower() + interface_name[1:]
        new_iter.generated = True
        self._api.components[interface_name] = new_iter
        self._write(
            """
            type {internal_struct} struct {{
                obj *{parent_internal_struct}
            }}

            type {interface} interface {{
                Add() {field_external_struct}
                Items() {field_type}
            }}

            func (obj *{internal_struct}) Add() {field_external_struct} {{
                newObj := &{pb_pkg_name}.{field_external_struct}{{}}
                obj.obj.obj.{field_name} = append(obj.obj.obj.{field_name}, newObj)
                return &{field_internal_struct}{{obj: newObj}}
            }}

            func (obj *{internal_struct}) Items() {field_type} {{
                slice := {field_type}{{}}
                for _, item := range obj.obj.obj.{field_name} {{
                    slice = append(slice, &{field_internal_struct}{{obj: item}})
                }}
                return slice
            }}
            """.format(
                internal_struct=new_iter.internal_struct,
                interface=new_iter.interface,
                field_internal_struct=field.struct,
                parent_internal_struct=new.struct,
                field_external_struct=field.external_struct,
                field_name=field.name,
                pb_pkg_name=self._protobuf_package_name,
                field_type=field.type,
            )
        )

    def _write_field_has(self, new, field):
        if field.has_method is None:
            return
        self._write(
            """
            // {fieldname} returns a {fieldtype}\n{description}
            func (obj *{struct}) Has{fieldname}() bool {{
                return obj.obj.{internal_field_name} != nil
            }}
            """.format(
                fieldname=self._get_external_struct_name(field.name),
                struct=new.struct,
                getter_method=field.getter_method,
                description=field.description,
                fieldtype=field.type,
                internal_field_name=field.name,
            )
        )

    def _build_setters_getters(self, fluent_new):
        """Add new FluentField objects for each interface field"""
        if "properties" not in fluent_new.schema_object:
            schema = self._get_parser("$..schema").find(fluent_new.schema_object)
            if len(schema) > 0:
                schema = schema[0].value
                schema_name = self._get_schema_object_name_from_ref(schema["$ref"])
                fluent_new.schema_object = {
                    "properties": {
                        self._get_external_struct_name(schema_name): schema,
                    },
                }
            else:
                return
        choice_enums = self._get_parser("$..choice..enum").find(fluent_new.schema_object["properties"])
        for property_name, property_schema in fluent_new.schema_object["properties"].items():
            field = FluentField()
            field.schema = property_schema
            field.description = self._get_description(property_schema)
            field.name = self._get_external_field_name(property_name)
            field.type = self._get_struct_field_type(property_schema)
            if len(choice_enums) == 1 and property_name in choice_enums[0].value:
                field.setChoiceValue = property_name.upper()
            else:
                field.setChoiceValue = None
            field.isEnum = len(self._get_parser("$..enum").find(property_schema)) > 0
            field.isArray = "type" in property_schema and property_schema["type"] == "array"
            if field.isEnum:
                field.enums = self._get_parser("$..enum").find(property_schema)[0].value
                if "unspecified" in field.enums:
                    field.enums.remove("unspecified")
            if fluent_new.isRpcResponse:
                if field.type == "[]byte":
                    field.name = "Bytes"
                elif "$ref" in property_schema:
                    schema_name = self._get_schema_object_name_from_ref(property_schema["$ref"])
                    field.name = self._get_external_struct_name(schema_name)
            field.isOptional = fluent_new.isOptional(property_name)
            field.isPointer = False if field.type.startswith("[") else field.isOptional
            if field.isArray and field.isEnum:
                field.getter_method = "{fieldname}() []{interface}{fieldname}Enum".format(
                    fieldname=self._get_external_struct_name(field.name),
                    interface=fluent_new.interface,
                )
            elif field.isEnum:
                field.getter_method = "{fieldname}() {interface}{fieldname}Enum".format(
                    fieldname=self._get_external_struct_name(field.name),
                    interface=fluent_new.interface,
                )
            else:
                field.getter_method = "{name}() {ftype}".format(
                    name=self._get_external_struct_name(field.name),
                    ftype=field.type,
                )
            if "$ref" in property_schema:
                schema_name = self._get_schema_object_name_from_ref(property_schema["$ref"])
                field.struct = self._get_internal_name(schema_name)
                field.external_struct = self._get_external_struct_name(schema_name)
            if field.isOptional and field.isPointer:
                field.has_method = """Has{fieldname}() bool""".format(
                    fieldname=self._get_external_struct_name(field.name),
                )
            if field.isArray and field.isEnum:
                field.setter_method = "Set{fieldname}(value []{interface}{fieldname}Enum) {interface}".format(
                    fieldname=self._get_external_struct_name(field.name),
                    interface=fluent_new.interface,
                )
            elif field.isEnum:
                field.setter_method = "Set{fieldname}(value {interface}{fieldname}Enum) {interface}".format(
                    fieldname=self._get_external_struct_name(field.name),
                    interface=fluent_new.interface,
                )
            elif field.type in self._oapi_go_types.values():
                field.setter_method = "Set{name}(value {ftype}) {interface}".format(
                    name=self._get_external_struct_name(field.name),
                    ftype=field.type,
                    interface=fluent_new.interface,
                )
            elif field.isArray:
                field.isPointer = False
                if "$ref" in property_schema["items"]:
                    schema_name = self._get_schema_object_name_from_ref(property_schema["items"]["$ref"])
                    field.isArray = True
                    field.struct = self._get_internal_name(schema_name)
                    field.external_struct = self._get_external_struct_name(schema_name)
                    field.adder_method = "Add() {parent}{external_struct}Iter".format(
                        parent=fluent_new.interface,
                        external_struct=field.external_struct,
                    )
                    field.isOptional = False
                    field.getter_method = "{name}() {parent}{external_struct}Iter".format(
                        name=self._get_external_struct_name(field.name),
                        parent=fluent_new.interface,
                        external_struct=field.external_struct,
                    )
                else:
                    field.setter_method = "Set{name}(value {ftype}) {interface}".format(
                        name=self._get_external_struct_name(field.name),
                        ftype=field.type,
                        interface=fluent_new.interface,
                    )
            fluent_new.interface_fields.append(field)

    def _get_schema_object_name_from_ref(self, ref):
        final_piece = ref.split("/")[-1]
        return final_piece.replace(".", "")

    def _get_schema_object_from_ref(self, ref):
        leaf = self._openapi
        for attr in ref.split("/")[1:]:
            leaf = leaf[attr]
        return leaf

    def _get_struct_field_type(self, property_schema, field=None):
        """Convert openapi type, format, items, $ref keywords to a go type"""
        go_type = ""
        if "type" in property_schema:
            oapi_type = property_schema["type"]
            if oapi_type.lower() in self._oapi_go_types:
                go_type = "{oapi_go_types}".format(oapi_go_types=self._oapi_go_types[oapi_type.lower()])
            if oapi_type == "array":
                go_type += "[]" + self._get_struct_field_type(property_schema["items"]).replace("*", "")
            if "format" in property_schema:
                format_type = (oapi_type + property_schema["format"]).lower()
                if format_type.lower() in self._oapi_go_types:
                    go_type = "{oapi_go_type}".format(oapi_go_type=self._oapi_go_types[format_type.lower()])
        elif "$ref" in property_schema:
            ref = property_schema["$ref"]
            schema_object_name = self._get_schema_object_name_from_ref(ref)
            schema_object = self._get_schema_object_from_ref(ref)
            new = None
            if schema_object_name in self._api.components:
                new = self._api.components[schema_object_name]
            else:
                new = FluentNew()
                new.schema_object = schema_object
                new.schema_name = schema_object_name
                new.struct = self._get_internal_name(schema_object_name)
                new.interface = self._get_external_struct_name(schema_object_name)
                self._api.components[new.schema_name] = new
            go_type = new.interface
        else:
            raise Exception("No type or $ref keyword present in property schema: {property_schema}".format(property_schema=property_schema))
        return go_type

    def _get_description(self, openapi_object):
        description = "//  description is TBD"
        if "description" in openapi_object:
            description = ""
            for line in openapi_object["description"].split("\n"):
                description += "//  {line}\n".format(line=line.strip())
        return description.strip("\n")

    def _format_go_file(self):
        """Format the generated go code"""
        try:
            process_args = [
                "goimports",
                "-w",
                self._filename,
            ]
            cmd = " ".join(process_args)
            print("Formatting generated go ux file: {}".format(cmd))
            process = subprocess.Popen(cmd, cwd=self._ux_path, shell=True)
            process.wait()
        except Exception as e:
            print("Bypassed formatting of generated go ux file: {}".format(e))

    def _tidy_mod_file(self):
        """Tidy the mod file"""
        try:
            process_args = [
                "go",
                "mod",
                "tidy",
            ]
            os.environ["GO111MODULE"] = "on"
            print("Tidying the generated go mod file: {}".format(" ".join(process_args)))
            process = subprocess.Popen(process_args, cwd=self._ux_path, shell=False, env=os.environ)
            process.wait()
        except Exception as e:
            print("Bypassed tidying the generated mod file: {}".format(e))
