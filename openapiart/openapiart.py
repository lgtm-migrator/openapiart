import sys
import os
import importlib
import shutil
import yaml
import subprocess
import requests


class OpenApiArt(object):
    """Bundle and generate artifacts from OpenAPI files.

    Args
    ----
    - api_files (list[str]): list of OpenAPI files that contain info and/or path
      keywords
    - python_module_name (str): name of the consolidated python file that will be generated
    - output_dir (str): directory where artifacts will be created.
      Unless otherwise specified the default directory for generated artifacts
      is `current working directory/.output`.
      The artifacts that will be generated are:
      - openapi.yaml
      - openapi.json
      - openapi.html (static documentation, if redoc-cli has been installed)
      - python package
      - protobuf file
      - python grpc
    """

    def __init__(
        self,
        api_files,
        python_module_name=None,
        protobuf_package_name=None,
        protobuf_file_name=None,
        go_module_name=None,
        output_dir=None,
        extension_prefix=None,
    ):
        self._python_module_name = python_module_name
        self._protobuf_file_name = protobuf_file_name
        self._protobuf_package_name = protobuf_package_name
        self._go_module_name = go_module_name
        self._extension_prefix = extension_prefix
        if output_dir is None:
            output_dir = os.path.join(os.getcwd(), ".output")
        self._relative_output_dir = output_dir
        self._output_dir = os.path.abspath(output_dir)
        shutil.rmtree(self._output_dir, ignore_errors=True)
        self._api_files = api_files
        self._bundle()
        self._get_license()
        self._get_info()
        self._document()
        self._generate()

    def _get_license(self):
        try:
            self._license = "License: {}".format(self._bundler._content["info"]["license"]["url"])
            return
            # currently license URL returns an HTML and not solely license text
            # hence skipping this part unless we come across a better way to
            # parse licenses
            response = requests.request("GET", self._bundler._content["info"]["license"]["url"])
            if response.ok:
                self._license = response.text
            else:
                raise Exception(response.text)
        except Exception as e:
            self._license = "OpenAPI info.license.url error [{}]".format(e)

    def _get_info(self):
        try:
            self._info = "{} {}".format(self._bundler._content["info"]["title"], self._bundler._content["info"]["version"])
        except Exception as e:
            self._info = "OpenAPI info error [{}]".format(e)

    def _bundle(self):
        # bundle the yaml files
        module = importlib.import_module("openapiart.bundler")
        bundler_class = getattr(module, "Bundler")
        self._bundler = bundler_class(api_files=self._api_files, output_dir=self._output_dir)
        self._bundler.bundle()
        # read the entire openapi file
        with open(self._bundler.openapi_filepath) as fp:
            self._openapi = yaml.safe_load(fp.read())

    def _document(self):
        """Try documenting the openapi using redoc-cli"""
        try:
            process_args = [
                "redoc-cli",
                "bundle",
                self._bundler.openapi_filepath,
                "--output",
                os.path.join(self._output_dir, "openapi.html"),
            ]
            subprocess.check_call(process_args, shell=True)
        except Exception as e:
            print("Bypassed creation of static documentation [missing redoc-cli]: {}".format(e))

    def _generate(self):
        # this generates the python ux module
        if self._python_module_name is not None:
            module = importlib.import_module("openapiart.generator")
            python_ux = getattr(module, "Generator")(
                self._bundler.openapi_filepath, self._python_module_name, output_dir=self._output_dir, extension_prefix=self._extension_prefix
            )
            python_ux.generate()

        # this generates protobuf definitions
        try:
            module = importlib.import_module("openapiart.openapiartprotobuf")
            protobuf = getattr(module, "OpenApiArtProtobuf")(
                **{
                    "info": self._info,
                    "license": self._license,
                    "python_module_name": self._python_module_name,
                    "protobuf_file_name": self._protobuf_file_name,
                    "protobuf_package_name": self._protobuf_package_name,
                    "go_module_name": self._go_module_name,
                    "output_dir": self._output_dir,
                }
            )
            protobuf.generate(self._openapi)
        except Exception as e:
            print("Bypassed creation of protobuf file: {}".format(e))

        # this generates the python stubs
        try:
            grpc_dir = os.path.normpath(os.path.join(self._output_dir, self._python_module_name))
            process_args = [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                "--python_out={}".format(grpc_dir),
                "--grpc_python_out={}".format(grpc_dir),
                "--proto_path={}".format(os.path.join(self._output_dir, "go")),
                "{}.proto".format(self._protobuf_file_name),
            ]
            print("Generating python grpc stubs: {}".format(" ".join(process_args)))
            subprocess.check_call(process_args, shell=False)
        except Exception as e:
            print("Bypassed creation of python stubs: {}".format(e))

        # this generates the go stubs
        try:
            protoc_out_dir = os.path.normpath(os.path.join(self._output_dir, "go", self._go_module_name))
            os.makedirs(protoc_out_dir)
            proto_path = os.path.normpath(os.path.join(self._output_dir, "go"))
            process_args = [
                "protoc",
                "--go_out={}".format(protoc_out_dir),
                "--go-grpc_out={}".format(protoc_out_dir),
                "--proto_path={}".format(proto_path),
                "--experimental_allow_proto3_optional",
                "{}.proto".format(self._protobuf_package_name),
            ]
            print("Generating go stubs: {}".format(" ".join(process_args)))
            subprocess.check_call(process_args, shell=False)
        except Exception as e:
            print("Bypassed creation of go stubs: {}".format(e))

        # this generates the go ux module
        try:
            module = importlib.import_module("openapiart.openapiartgo")
            go_ux = getattr(module, "OpenApiArtGo")(
                **{
                    "info": self._info,
                    "license": self._license,
                    "python_module_name": self._python_module_name,
                    "protobuf_file_name": self._protobuf_file_name,
                    "protobuf_package_name": self._protobuf_package_name,
                    "go_module_name": self._go_module_name,
                    "output_dir": self._output_dir,
                }
            )
            go_ux.generate(self._openapi)
        except Exception as e:
            print("Bypassed creation of go ux module: {}".format(e))

    @property
    def output_dir(self):
        return self._output_dir

    @property
    def python_module_name(self):
        return self._python_module_name
