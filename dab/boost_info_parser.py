#
# Copyright (C) 2014 Regents of the University of California.
# Author: Adeola Bannis
# Edit by: Copyright (C) 2021 Bastiaan Teeuwen <bastiaan@mkcl.nl>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# A copy of the GNU General Public License is in the file COPYING.

import copy
import shlex
from collections import OrderedDict

class BoostInfoTree(object):
    def __init__(self, value=None, parent=None):
        super(BoostInfoTree, self).__init__()
        self.subTrees = OrderedDict()
        self.value = value
        self.parent = parent

        self.lastChild = None

    def __copy__(self):
        out = self.__class__.__new__(self.__class__)
        out.__dict__.update(self.__dict__)

        return out
    def __deepcopy__(self, memo):
        out = self.__class__.__new__(self.__class__)
        memo[id(self)] = out

        for key, value in self.__dict__.items():
            setattr(out, key, copy.deepcopy(value, memo))

        return out

    def __len__(self):
        if self.value is None:
            return len(self.subTrees)
        else:
            return len(self.value)

    def __setitem__(self, key, value=None):
        newtree = BoostInfoTree(value, self)
        if key in self.subTrees:
            self.subTrees[key][0].value = value
        else:
            self.subTrees[key] = [newtree]
            self.lastChild = newtree
    def __setattr__(self, key, value=None):
        if key in ('subTrees', 'value', 'parent', 'lastChild'):
            return object.__setattr__(self, key, value)
        return self.__setitem__(key, value)

    def __getitem__(self, key):
        try:
            assert self.subTrees[key][0]
        except (KeyError, AssertionError):
            self.__setitem__(key, None)

        return self.subTrees[key][0]
        #if tree.value is not None and len(tree.value) > 0:
        #    return tree.value
        #else:
        return tree
    def __getattr__(self, key):
        if key in ('subTrees', 'value', 'parent', 'lastChild'):
            return object.__getattr__(self, key)
        return self.__getitem__(key)

    def __iter__(self):
        return iter(self.subTrees.items())

    def __delitem__(self, key):
        del self.subTrees[key]

    def _prettyprint(self, indentLevel=1, first=True):
        prefix = ' ' * indentLevel
        s = ''
        if self.parent is not None:
            if self.value is not None and len(self.value) > 0:
                s += '"' + str(self.value) + '"'
            s+= '\n'
        if len(self.subTrees) > 0:
            if self.parent is not None:
                s += prefix + '{\n'
            nextLevel = ' ' * (indentLevel + 2)
            for t in self.subTrees:
                for subTree in self.subTrees[t]:
                    s += nextLevel + str(t) + ' ' + subTree._prettyprint(indentLevel + 2, False)
            if self.parent is not None:
                s +=  prefix + '}\n'
        elif first:
            return s[1:-2]

        return s[:-1] if first else s

    def __str__(self):
        return self._prettyprint()


class BoostInfoParser(object):
    def __init__(self):
        self._reset()

    def _reset(self):
        self._root = BoostInfoTree()
        self._root.lastChild = self

    def load(self, root):
        self._root = root

    def read(self, filename):
        with open(filename, 'r') as stream:
            ctx = self._root
            for line in stream:
                ctx = self._parseLine(line.strip(), ctx)

    def write(self, filename):
        with open(filename, 'w') as stream:
            stream.write(str(self._root))

    def _parseLine(self, string, context):
        # skip blank lines and comments
        commentStart = string.find(';')
        if commentStart >= 0:
           string = string[:commentStart].strip()
        if len(string) == 0:
           return context

        # ok, who is the joker who put a { on the same line as the key name?!
        sectionStart = string.find('{')
        if sectionStart > 0:
            firstPart = string[:sectionStart]
            secondPart = string[sectionStart:]

            ctx = self._parseLine(firstPart, context)
            return self._parseLine(secondPart, ctx)

        #if we encounter a {, we are beginning a new context
        # TODO: error if there was already a subcontext here
        if string[0] == '{':
            context = context.lastChild
            return context

        # if we encounter a }, we are ending a list context
        if string[0] == '}':
            context = context.parent
            return context

        # else we are expecting key and optional value
        strings = shlex.split(string)
        key = strings[0]
        if len(strings) > 1:
            val = strings[1]
        else:
            val = None
        context[key] = val

        return context

    def getRoot(self):
        return self._root

    def __getitem__(self, key):
        ctxList = [self._root]
        path = key.split('/')
        foundVals = []
        for k in path:
            newList = []
            for ctx in ctxList:
                try:
                    newList.extend(ctx[k])
                except KeyError:
                    pass
            ctxList = newList

        return ctxList
