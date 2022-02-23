#!/usr/bin/env python
'''analyse_cc4s.py [options] directory_1 directory_2 ... directory_N

Perform sFTA on a list of user provided directories which 
contain cc4s structure factor outputs `GridVectors.elements`,
`CoulombPotential.elements`, and `SF.elements`.

The final report provides the directory for the structure factor 
data which minimizes the residual of the difference between the 
average structure factor and the given individual structure factor.

More details can be found in: https://doi.org/10.1038/s43588-021-00165-1
'''

import os
import sys
import time
import argparse
import numpy as np
import pandas as pd


class AnalysisTimer:
    ''' A simple timer for the analysis script.'''
    def __init__(self):
        ''' Initialize the timer instance.

        Parameters
        ----------
        None.
        '''
        self.initial_time = time.perf_counter()
    def end(self):
        ''' Calculate the total time in minutes, and report'''
        self.final_time = time.perf_counter()
        self.total_time = (self.final_time - self.initial_time)/60.0
        print(f' Script execution time: {self.total_time:>8.4f} (minutes)')


def parse_command_line_arguments(arguments):
    ''' Parse command-line arguments.

Parameters
----------
arguments : list of strings
    User provided command-line arguments.

Returns
-------
directories : list of strings
    The directories where structure factor data is contained.
options : :class:`ArgumentParser`
    User options read in from the command-line.
'''
    parser = argparse.ArgumentParser(usage = __doc__)
    parser.add_argument('-w', '--write', action='store', default=None,
                        type=str, dest='write', help='A file to write the '
                        'individual structure factor data, in a format '
                        'ammendable to the sfTA.py script.')
    parser.add_argument('directories', nargs='+', help='Paths containing '
                        'Structure Factor data to be analyzed.')
    parser.parse_args(args=None if arguments else ['--help'])

    options = parser.parse_args(arguments)

    return options.directories, options


def find_SF_outputs(directories):
    ''' Search through the user provided directories and find the relevenant
        outputs for sFTA.

Parameters
----------
directories : list of strings
    The directories where structure factor data is contained.

Returns
-------
Gvector_files : list of strings
    A list of files with the G vector data.
Coulomb_files : list of strings
    A list of files with the Coulomb potential data.
S_G_files : list of strings
    A list of files with the S_G data.
'''
    Gvector_files, Coulomb_files, S_G_files = [], [], []
    for path in directories:
        Gvector_file = f'{path}/GridVectors.elements'
        Coulomb_file = f'{path}/CoulombPotential.elements'
        S_G_file = f'{path}/SF.elements'

        if not os.path.isfile(Gvector_file):
            raise ValueError(f'{Gvector_file} does not exist!')
        elif not os.path.isfile(Coulomb_file):
            raise ValueError(f'{Coulomb_file} does not exist!')
        elif not os.path.isfile(S_G_file):
            raise ValueError(f'{S_G_file} does not exist!')
        else:
            Gvector_files.append(Gvector_file)
            Coulomb_files.append(Coulomb_file)
            S_G_files.append(S_G_file)

    return Gvector_files, Coulomb_files, S_G_files


def read_and_generate_Gvector_magnitudes(Gvector_file):
    ''' Read in a GridVectors.elements file generated by cc4s and calculate the
        G magnitudes for sFTA.

Parameters
----------
Gvector_file : string
    A file which contains the G vectors.

Returns
-------
G : :class:`numpy.ndarray`
    An array of the G magnitudes.
'''
    raw_g_xyz = np.loadtxt(Gvector_file, dtype=np.float64)
    N_G = int(raw_g_xyz.shape[0] / 3)
    g_xyz = raw_g_xyz.reshape((N_G, 3))
    G = np.sqrt(np.einsum('ij,ij->i', g_xyz, g_xyz))

    return G


def read_Vg(Coulomb_files):
    ''' Read in a CoulombPotenial.elements file generated by cc4s.

Parameters
----------
Coulomb_files : string
    A file which contains the Coulomb energy elements.

Returns
-------
V_G : :class:`numpy.ndarray`
    An array of the Coulomb potential values for the G magnitudes.
'''
    V_G = np.loadtxt(Coulomb_files, dtype=np.float64)

    return V_G


def read_Sg(S_G_file):
    ''' Read in a SF.elements file generated by cc4s.

Parameters
----------
S_G_file : string
    A file which contains the Structure Factor elements.

Returns
-------
S_G : :class:`numpy.ndarray`
    An array of the Structure Factor values for the G magnitudes.
'''
    S_G = np.loadtxt(S_G_file, dtype=np.float64)

    return S_G


def read_and_average_SF(Gvector_files, Coulomb_files, S_G_files):
    ''' Loop through the relevant files of structure factors and calculate
        the average structure factor.

Parameters
----------
Gvector_files : list of strings
    A list of files with the G vector data.
Coulomb_files : list of strings
    A list of files with the Coulomb energy data.
S_G_files : list of strings
    A list of files with the S_G data.

Returns
-------
raw_SF : list of :class:`pandas.DataFrame`
    A pandas data frame of all structure factors concatenated together.
SF : :class:`pandas.DataFrame`
    A data frame of the average structure factor.
'''
    raw_SF = []
    for files in zip(Gvector_files, Coulomb_files, S_G_files):
        G = read_and_generate_Gvector_magnitudes(files[0])
        V_G = read_Vg(files[1])
        S_G = read_Sg(files[2])
        SFi = pd.DataFrame({'G':G.round(10), 'V_G':V_G, 'S_G':S_G})
        raw_SF.append(SFi)

    group = pd.concat(raw_SF).groupby('G', as_index=False)
    SF = group.mean()
    SF[['G_error', 'V_G_error', 'S_G_error']] = group.sem()[['G', 'V_G', 'S_G']]

    return raw_SF, SF


def find_special_twist_angle(raw_SF, SF):
    ''' Find the twist angle corresponding to the minimum residual
        between the twist averaged S_G and a given S_G.

Parameters
----------
raw_SF : list of :class:`pandas.DataFrame`
    A pandas data frame of all structure factors concatenated together.
SF : :class:`pandas.DataFrame`
    A data frame of the average structure factor.

Returns
-------
special_twist_index : integer
    The index of the special twist angle. The index is pythonic and
    matches the various lists used throughout.
'''
    residuals = []
    for SFi in raw_SF:
        aSFi = SFi.groupby('G', as_index=False).mean()
        residuals.append(np.power(np.abs(SF['S_G'] - aSFi['S_G']), 2).sum())

        if not np.array_equal(aSFi['G'], SF['G']):
            raise ValueError('G value arrays are not equivlent between'+\
                                'the average SF and an individual SF.'+\
                                'This should not happen!')

    special_twist_index = np.argmin(residuals)

    return special_twist_index


def write_sfTA_csv(csv_file, directories, raw_SF):
    ''' Write out the raw structure factor data in a format
        which is ammendable to sfTA.py.

Parameters
----------
csv_file : str
    A user provided name to save the data to.
directories : list of strings
    The directories where structure factor data is contained.
raw_SF : list of :class:`pandas.DataFrame`
    A pandas data frame of all structure factors concatenated together.

Returns
-------
None.
'''
    if '.csv' not in csv_file:
        csv_file += '.csv'

    csv_twist = csv_file.replace('.csv', '_Twist_angle_Num_map.csv')

    csv_SF, csv_mp = [], {'Twist angle Num':[], 'directory':[]}
    for i, (SFi, directory) in enumerate(zip(raw_SF, directories)):
        itwist = np.repeat(i+1, SFi['G'].shape[0])
        oSFi = pd.DataFrame({'Twist angle Num':itwist})
        oSFi[['G', 'V_G', 'S_G']] = SFi[['G', 'V_G', 'S_G']]
        csv_SF.append(oSFi.sort_values(by='G').reset_index(drop=True))

        csv_mp['Twist angle Num'].append(i+1)
        csv_mp['directory'].append(directory)

    print(f' Saving structure factor data to: {csv_file}')
    pd.concat(csv_SF).to_csv(csv_file, index=False)
    print(f' Saving twist angle index map to: {csv_twist}')
    pd.DataFrame(csv_mp).to_csv(csv_twist, index=False)


def main(arguments):
    ''' Run structure factor twist averaging on cc4s outputs.

Parameters
----------
arguments : list of strings
    User provided command-line arguments.

Returns
-------
None.
'''
    directories, options = parse_command_line_arguments(arguments)

    Gvector_files, Coulomb_files, S_G_files = find_SF_outputs(directories)

    raw_SF, SF = read_and_average_SF(Gvector_files, Coulomb_files, S_G_files)

    special_twist_index = find_special_twist_angle(raw_SF, SF)

    if options.write is not None:
        write_sfTA_csv(options.write, directories, raw_SF)

    print(f'\n Found Special Twist Angle:')
    print(f' {directories[special_twist_index]}\n')


if __name__ == '__main__':
    timer = AnalysisTimer()
    main(sys.argv[1:])
    timer.end()
