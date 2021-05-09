#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2021 Kinu Garage

import datetime
import logging
import os
from pathlib import Path
import pytest
import time

# Hacky/inappropriate way to import.
from docker_builder_vcs import DockerBuilderVCS


class TestDockerBuilderVCS():

    def test_copy(self):
        """
        @summary: TBD
        """
        tmp_dir = "/tmp/{}".format(datetime.datetime.fromtimestamp(time.time()).strftime('%Y%m%d%H%M%S'))
        list_files_src = []
        path_file_aaa = "/tmp/file.aaa" 
        Path(path_file_aaa).touch()
        path_file_bbb = "/tmp/file.bbb"
        Path(path_file_bbb).touch()
        path_folder_aaa = "/tmp/folder_aaa"
        os.makedirs(path_folder_aaa, exist_ok=True)
        list_files_src.append(path_file_aaa)
        list_files_src.append(path_file_bbb)
        list_files_src.append(path_folder_aaa)

        dbv = DockerBuilderVCS()
        ret = dbv.copy(tmp_dir, list_files_src)
        assert isinstance(ret, str)

    def test_build_result_parser(self):
        dbuild_res = [b'{"stream":"Step 1/30 : ARG BASE_DIMG"}\r\n{"stream":"\\n"}\r\n{"stream":"Step 2/30 : FROM ${BASE_DIMG}"}\r\n{"stream":"\\n"}\r\n{"stream":" ---\\u003e f8333a8caf28\\n"}\r\n{"stream":"Step 3/30 : SHELL [\\"/bin/bash\\", \\"-c\\"]"}\r\n{"stream":"\\n"}\r\n{"stream":" ---\\u003e Using cache\\n"}\r\n{"stream":" ---\\u003e b321d3a27cdb\\n"}\r\n{"stream":"Step 4/30 : ARG ENTRY_POINT=entry_point.bash"}\r\n{"stream":"\\n"}\r\n{"stream":" ---\\u003e Using cache\\n"}\r\n{"stream":" ---\\u003e 9192520473ae\\n"}\r\n{"stream":"Step 5/30 : ARG ROSDISTRO=\\"melodic\\""}\r\n{"stream":"\\n"}\r\n{"stream":" ---\\u003e Using cache\\n"}\r\n{"stream":" ---\\u003e d5431da209d3\\n"}\r\n"}\r\n', b'{"errorDetail":{"message":"COPY failed: file not found in build context or excluded by .dockerignore: stat entry_point.bash: file does not exist"},"error":"COPY failed: file not found in build context or excluded by .dockerignore: stat entry_point.bash: file does not exist"}\r\n']
        len_dbuild_res = 21  # This is the num of lines when '\r\n' is replaced with carriage return in 'dbuild_res'.
        list_str = DockerBuilderVCS.build_result_parser(dbuild_res)
        assert len_dbuild_res == len(list_str)
