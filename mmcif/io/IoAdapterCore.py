##
# File: IoAdapterCore.py
# Date: 20-Jan-2013  John Westbrook
#
# Updates:
# 20-Jan-2013 jdw Type convert to string or '?'
#  7-May-2014 jdw Make output line length 2048
# 30-Jul-2014 jdw Expose maximum line length as an optional writeFile() parameter.
#  5-Feb-2015 jdw disable maximum line length parameter -
#  6-Dec-2015 jdw add detailed timers
#  6-Dec-2015 jdw add additional filters for category write order -
# 28-Jul-2016 rps readFile(), __readData() methods updated to accept optional "logtag" parameter
# 15-Feb-2017 ep  Correct variable name in exception in __readDataSelect()
#  8-Jan-2018 jdw adapt to new pybind11 bindings -  change logging framework -- handle py2->3
# 10-Jan-2018 jdw complete rewrite for new mmciflib framework.
#
##
"""
Adapter between Python mmCIF API and Pybind11 wrappers for the PDB C++ Core mmCIF Library.

"""
from __future__ import absolute_import
from six.moves import range

__docformat__ = "restructuredtext en"
__author__ = "John Westbrook"
__email__ = "john.westbrook@rcsb.org"
__license__ = "Apache 2.0"

import sys
import time
import os
from future.utils import raise_from

import logging
logger = logging.getLogger(__name__)

HERE = os.path.abspath(os.path.dirname(__file__))


from mmcif.io.IoAdapterBase import IoAdapterBase

from mmcif.api.PdbxContainers import *
from mmcif.api.DataCategory import DataCategory
from mmcif.io.PdbxExceptions import PdbxError, SyntaxError

try:
    from mmcif.core.mmciflib import ParseCifSimple, CifFile, ParseCifSelective, type, CifFileReadDef
except Exception as e:
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from build.lib.mmciflib import ParseCifSimple, CifFile, ParseCifSelective, type, CifFileReadDef


class IoAdapterCore(IoAdapterBase):
    """ Adapter between Python mmCIF API and Pybind11 wrappers for the PDB C++ Core mmCIF Library.
    """

    def __init__(self, *args, **kwargs):
        super(IoAdapterCore, self).__init__(*args, **kwargs)

    def readFile(self, inputFilePath, enforceAscii=True, selectList=None, excludeFlag=False, logFilePath=None, outDirPath=None, cleanUp=True, **kwargs):
        """Parse the data blocks in the input mmCIF format data file into list of DataContainers().  The data category content within each data block
           is stored a collection of DataCategory objects within each DataContainer.

        Args:
            inputFilePath (string): Input file path
            enforceAscii (bool, optional): Flag to requiring pre-filtering operation to convert input file to ASCII encoding. See encoding error options.
            selectList (List, optional):  List of data category names to be extracted or excluded from the input file (default: select/extract)
            excludeFlag (bool, optional): Flag to indicate selectList should be treated as an exclusion list
            logFilePath (string, optional): Log file path (if not provided this will be derived from the input file.)
            outDirPath (string, optional): Path for translated/reencoded files and default logfiles.
            cleanUp (bool, optional): Flag to automatically remove logs and temporary files on exit.
            **kwargs: Placeholder for missing keyword arguments.

        Returns:
            List of DataContainers: Contents of input file parsed into a list of DataContainer objects.
        """
        if len(kwargs):
            logger.warn("Unsupported keyword arguments %s" % kwargs.keys())
        asciiFilePath = None
        filePath = str(inputFilePath)
        try:
            #
            lPath = logFilePath
            if not lPath:
                lPath = self._getDefaultFileName(filePath, fileType='cif-parser-log', outDirPath=outDirPath)
            #
            self._setLogFilePath(lPath)
            #
            if not self._fileExists(filePath):
                return []
            #
            tPath = filePath
            if enforceAscii:
                asciiFilePath = self._getDefaultFileName(filePath, fileType='cif-parser-ascii', fileExt='cif', outDirPath=outDirPath)
                encodingErrors = 'xmlcharrefreplace' if self._useCharRefs else 'ignore'
                logger.debug("Filtering input file to %s using encoding errors as %s" % (asciiFilePath, encodingErrors))
                ok = self._toAscii(filePath, asciiFilePath, chunkSize=5000, encodingErrors=encodingErrors)
                if ok:
                    tPath = asciiFilePath
            #
            readDef = None
            if selectList and len(selectList) > 0:
                readDef = self.__getSelectionDef(selectList, excludeFlag)
            #
            containerL, diagL = self.__readData(tPath, readDef=readDef, cleanUp=cleanUp, logFilePath=lPath, maxLineLength=self._maxInputLineLength)
            #
            self._cleanupFile(asciiFilePath and cleanUp, asciiFilePath)
            #
            return containerL
        except (PdbxError, SyntaxError) as ex:
            self._cleanupFile(asciiFilePath and cleanUp, asciiFilePath)
            if self._raiseExceptions:
                raise_from(ex, None)
                # raise ex from None
        except Exception as e:
            self._cleanupFile(asciiFilePath and cleanUp, asciiFilePath)
            msg = "Failing read for %s with %s" % (filePath, str(e))
            self._logError(msg)

        return []

    def getReadDiags(self):
        """Recover the diagnostics for the previous readFile() operation.readFile

           Returns:
             list of strings:  List of parsing and processing diagnostics from last readFile() operation
        """
        return self._readLogRecords()

    def __getSelectionDef(self, selectList, excludeFlag):
        """ Internal method to package selection/exclusion list for the C++ parser library.

            Returns:
               CifFileReadDef() object:  object prepared for parsing library
        """
        try:
            readDef = CifFileReadDef()
            if excludeFlag:
                readDef.SetCategoryList(selectList, type.D)
            else:
                readDef.SetCategoryList(selectList, type.A)
            return readDef
        except Exception as e:
            msg = "Failing read selection with %s" % str(e)
            self._logError(msg)
        return None

    def __processReadLogFile(self, inputFilePath):
        """ Internal method to process logfiles and either log errors or raise exceptions (See: Class PdbxExceptions).
            The behavior is controlled by the class attribute _raiseExcetions.

            Returns:
             list of strings:  List of records in the input log file
        """
        diagL = self._readLogRecords()
        #
        if diagL:
            numErrors = 0
            numSyntaxErrors = 0
            numWarnings = 0
            for diag in diagL:
                if 'ERROR' in diag:
                    numErrors += 1
                if 'WARN' in diag:
                    numWarnings += 1
                if 'syntax' in diag.lower():
                    numSyntaxErrors += 1
            #
            logger.debug("%s syntax errors %d  warnings %d all errors %d" % (inputFilePath, numSyntaxErrors, numWarnings, numErrors))
            #
            if numSyntaxErrors and self._raiseExceptions:
                raise SyntaxError("%s syntax errors %d  all errors %d" % (inputFilePath, numSyntaxErrors, numErrors))
            elif numErrors and self._raiseExceptions:
                raise PdbxError("%s error count is %d" % (inputFilePath, numErrors))
            elif numErrors:
                logger.error("%s syntax errors %d  all errors %d" % (inputFilePath, numSyntaxErrors, numErrors))
            if numWarnings:
                logger.warn("%s warnings %d" % (pdbxFilePath, numWarnings))

        return diagL

    def __processContent(self, cifFileObj):
        """Internal method to transfer parsed data from the wrapped input C++ CifFile object into
        the list of Python DataContainer objects.

        Args:
            cifFileObj (wrapped CifFile object): Wrapped input C++ CifFile object

        Returns:
            list of DataContainer objects:   List of Python DataContainer objects

        """
        containerList = []
        containerNameList = []
        try:
            # ----- Repackage the data content  ----
            #
            containerList = []
            containerNameList = []
            containerNameList = list(cifFileObj.GetBlockNames(containerNameList))
            for containerName in containerNameList:
                #
                aContainer = DataContainer(containerName)
                #
                block = cifFileObj.GetBlock(containerName)
                tableNameList = []
                tableNameList = list(block.GetTableNames(tableNameList))

                for tableName in tableNameList:
                    table = block.GetTable(tableName)
                    attributeNameList = list(table.GetColumnNames())
                    numRows = table.GetNumRows()
                    rowList = []
                    for iRow in range(0, numRows):
                        row = table.GetRow(iRow)
                        # row = table.GetRow(iRow).decode('unicode_escape').encode('utf-8')
                        # row = [p.encode('ascii', 'xmlcharrefreplace') for p in table.GetRow(iRow)]
                        rowList.append(list(row))
                    aCategory = DataCategory(tableName, attributeNameList, rowList, copyInputData=False)
                    aContainer.append(aCategory)
                containerList.append(aContainer)
        except Exception as e:
            msg = "Failing packaging with %s" % str(e)
            self._logError(msg)

        return containerList

    def __readData(self, inputFilePath, readDef=None, maxLineLength=1024, logFilePath=None, cleanUp=False):
        """Internal method to read input file and return data as a list of DataContainer objects.
        readDef optionally contains a selection of data categories to be returned.    Diagnostics
        will be written to logFilePath (persisted if cleanuUp=False).

        Args:
            inputFilePath (string):  input file path
            readDef (CifFileReadDef object, optional): wrapped CifFileReadDef() object
            maxLineLength (int, optional): Maximum supported line length on input
            logFilePath (string, optional): Log file path
            cleanUp (bool, optional): Flag to remove temporary files on exit

        Returns:
            Tuple of lists : DataContainer List, Diagnostics (string) List

        """
        #
        startTime = time.clock()
        containerList = []
        diagL = []
        try:
            if readDef:
                cifFileObj = ParseCifSelective(
                    inputFilePath,
                    readDef,
                    verbose=self._verbose,
                    intCaseSense=0,
                    maxLineLength=maxLineLength,
                    nullValue="?",
                    parseLogFileName=logFilePath)
            else:
                cifFileObj = ParseCifSimple(inputFilePath, verbose=self._verbose, intCaseSense=0, maxLineLength=maxLineLength, nullValue="?", parseLogFileName=logFilePath)
            #
            # ---  Process/Handle read errors   ----
            #
            diagL = self.__processReadLogFile(inputFilePath)
            logger.debug("Diagnostic count %d values %r" % (len(diagL), diagL))
            #
            if self._timing:
                stepTime1 = time.clock()
                logger.info("Timing parsed %r in %.4f seconds" % (inputFilePath, stepTime1 - startTime))
            #
            containerList = self.__processContent(cifFileObj)
            #
            self._cleanupFile(cleanUp, logFilePath)
            if self._timing:
                stepTime2 = time.clock()
                logger.info("Timing api load in %.4f seconds read time %.4f seconds\n" %
                            (stepTime2 - stepTime1, stepTime2 - startTime))
            #
            return containerList, diagL
        except (PdbxError, SyntaxError) as ex:
            self._cleanupFile(cleanUp, logFilePath)
            if self._raiseExceptions:
                raise_from(ex, None)
        except Exception as e:
            self._cleanupFile(cleanUp, logFilePath)
            msg = "Failing read for %s with %s" % (inputFilePath, str(e))
            self._logError(msg)

        return containerList, diagL

    def writeFile(self, outputFilePath, containerList=None, maxLineLength=900, enforceAscii=True,
                  lastInOrder=['pdbx_nonpoly_scheme', 'pdbx_poly_seq_scheme', 'atom_site', 'atom_site_anisotrop'], selectOrder=None, **kwargs):
        """Write input list of data containers to the specified output file path in mmCIF format.

        Args:
            outputFilePath (string): output file path
            containerList (list DataContainer objects, optional):
            maxLineLength (int, optional): Maximum length of output line (content is wrapped beyond this length)
            enforceAscii (bool, optional): Filter output (not implemented - content must be ascii compatible on input)
            lastInOrder (list of category names, optional): Move data categories in this list to end of each data block
            selectOrder (list of category names, optional): Write only data categories on this list.
            **kwargs: Placeholder for unsupported key value pairs

        Returns:
            bool: Completion status


        """
        containerL = containerList if containerList else []
        if len(kwargs):
                logger.warn("Unsupported keyword arguments %s" % kwargs.keys())
        try:
            startTime = time.clock()
            logger.debug("write container length %d\n" % len(containerL))
            # (CifFile args: placeholder, verbose: bool, caseSense: Char::eCompareType, maxLineLength: int, nullValue: str)
            cF = CifFile(True, self._verbose, 0, maxLineLength, '?')
            for container in containerL:
                containerName = container.getName()
                logger.debug("writing container %s\n" % containerName)
                cF.AddBlock(containerName)
                block = cF.GetBlock(containerName)
                #
                # objNameList = container.getObjNameList()
                # logger.debug("write category length %d\n" % len(objNameList))
                #
                # Reorder/Filter - container object list-
                objNameList = container.filterObjectNameList(lastInOrder=lastInOrder, selectOrder=selectOrder)
                logger.debug("write category names  %r\n" % objNameList)
                #
                for objName in objNameList:
                    name, attributeNameList, rowList = container.getObj(objName).get()
                    table = block.AddTable(name)
                    for attributeName in attributeNameList:
                        table.AddColumn(attributeName)
                    try:
                        rLen = len(attributeNameList)
                        for ii, row in enumerate(rowList):
                            table.AddRow()
                            table.FillRow(ii, [str(row[jj]) if row[jj] is not None else '?' for jj in range(0, rLen)])
                    except Exception as e:
                        logger.error("Exception for %s preparing data for writing %s" % (outputFilePath, str(e)))
                    #
                    block.WriteTable(table)
            #
            if self._timing:
                stepTime1 = time.clock()
                logger.info("Timing %d container(s) api loaded in %.4f seconds" % (len(containerL), stepTime1 - startTime))
            if (self._debug):
                self.__dumpBlocks(cF)
            cF.Write(str(outputFilePath))
            if self._timing:
                stepTime2 = time.clock()
                logger.info("Timing %d container(s) written in %.4f seconds total time %.4f" %
                            (len(containerList), stepTime2 - stepTime1, stepTime2 - startTime))
            return True

        except Exception as e:
            msg = "Write failing for file %s with %s" % (outputFilePath, str(e))
            self._logError(msg)
        return False

    def __dumpBlocks(self, cf):
        """Internal method to log the contents of the input wrapped CifFile object.

        Args:
            cf (CifFile object): wrapped CifFile object.
        """
        try:
            logger.info("cif file %r" % cf)
            blockNameList = []
            blockNameList = cf.GetBlockNames(blockNameList)
            #
            logger.info(" block name list %r" % repr(blockNameList))
            for blockName in blockNameList:
                #
                block = cf.GetBlock(blockName)
                tableNameList = []
                tableNameList = list(block.GetTableNames(tableNameList))
                logger.info("tables name list %r" % repr(tableNameList))
                for tableName in tableNameList:
                    logger.info("table name %r" % tableName)
                    ok = block.IsTablePresent(tableName)
                    logger.info("table present %r" % ok)
                    table = block.GetTable(tableName)

                    attributeNameList = list(table.GetColumnNames())
                    logger.info("Attribute name list %r" % repr(attributeNameList))
                    numRows = table.GetNumRows()
                    logger.info("row length %r" % numRows)
                    for iRow in range(0, numRows):
                        row = table.GetRow(iRow)
                        logger.info("Attribute name list %r" % row)
        except Exception as e:
            logger.exception("dump failing with %s\n" % str(e))


if __name__ == '__main__':
    pass