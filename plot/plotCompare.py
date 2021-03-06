import matplotlib
matplotlib.rcParams['backend'] = 'Agg'
import boomslang
import numpy

from expsiftUtils import *


# Returns a boomslang ClusteredBars() object to which the specified Bars have
# been added.
def clusteredBarsGraph(bars, xTickLabels, spacing=0.5):
    clusteredBars = boomslang.ClusteredBars()
    clusteredBars.spacing = spacing
    for bar in bars:
        clusteredBars.add(bar)
    clusteredBars.xTickLabels = xTickLabels
    return clusteredBars


# Returns a boomslang Bar() object with the specified parameters
def barGraph(xValues, yValues, yErrors,
             label='Bar', color='red', errorBarColor='black'):
    bar = boomslang.Bar()
    bar.xValues = xValues
    bar.yValues = yValues
    bar.yErrors = yErrors
    bar.color = color
    bar.errorBarColor = errorBarColor
    bar.label = label
    return bar


# Plot comparison graph across different configurations.
#
# Hierarchy:
# - subplot_props: Separate clusterbar subplot for each unique combination of
#                  values for properties in subplot_props [provided as argument
#                  to the function]
# - majorgroup: Separate bargraph for each major group
#               [computed based on the properties specified in
#               subplot_props, cluster_props, and trial_props]
# - cluster_props: Separate xTickLocation or cluster for each unique combination
#                  of values for properties in cluster_props (provided as
#                  argument to the function)
# - trial_props: For each (subplot, majorgroup and cluster) combination, we
#                plot along y-axis, the average and stddev across all
#                directories which only different in the values of properties
#                specified in trial_props and which match the particular
#                (subplot, majorgroup and cluster) combination
#                [provided as argument to the function]
#
# majorgroup of a directory: Ignore the properties in subplot_props,
# cluster_props, and trial_props. The other properties constitute the
# majorgroup. Each majorgroup is denoted by a frozenset of prop=val strings that
# are unique to the majorgroup.
#
# Returns a tuple: (unique_subplot_titles,
#                   unique_majorgroup_labels,
#                   unique_cluster_labels,
#                   clusterdir_dict,
#                   PlotLayout)
# - unique_subplot_titles, unique_majorgroup_labels, unique_cluster_labels are
#   sorted in the order used for the actual graphs.
# - clusterdir_dict indicates the directory grouping that was actually used to
#   plot the graph.
# - PlotLayout is the actual graph with multiple subplots.
def plotClusterBarComparisonDirs(dir2props_dict, # dict
                                 subplot_props,  # list
                                 cluster_props,  # list
                                 trial_props,    # list
                                 fn_sort_subplots,
                                 fn_sort_clusters,
                                 fn_sort_majorgroups,
                                 fn_get_subplot_title,
                                 fn_get_cluster_label,
                                 fn_get_majorgroup_label,
                                 fn_get_datapoint,
                                 xLabel,
                                 yLabel,
                                 layout = None):

    # 1. Turn each directory's set of prop=val strings into a dictionary to
    #     easily look up the value of a particular property for the directory
    dir2prop2val_dict = getDir2Prop2ValDict(dir2props_dict)


    # 2. Find all the common and unique properties among all directories
    common_props, unique_props = getCommonAndUniqueProperties(dir2props_dict)


    # 3A. Find all unique values of the subplot properties
    subplot2dir_dict = getDirGroupsByProperty(dir2props_dict, subplot_props,
                                              ignore = False)
    unique_subplots = subplot2dir_dict.keys()
    # 3B. Sort the subplots
    fn_sort_subplots(unique_subplots)


    # 4. Find all unique values of the cluster properties
    cluster2dir_dict = getDirGroupsByProperty(dir2props_dict, cluster_props,
                                              ignore = False)
    unique_clusters = cluster2dir_dict.keys()
    # 4B. Sort the clusters
    fn_sort_clusters(unique_clusters)


    # 5. Find all unique major groupings or configurations:
    #    Ignore the properties in subplot_props, cluster_props, and
    #    trial_props. The other properties constitute the majorgroup.
    #    Each majorgroup is denoted by a frozenset of prop=val strings that
    #    are unique to the majorgroup.
    majorgroup2dir_dict = getDirGroupsByProperty(
            dir2props_dict,
            subplot_props + cluster_props + trial_props,
            ignore = True)
    unique_majorgroups = majorgroup2dir_dict.keys()


    # 6A. Allocate a separate xValue in the graphs for each cluster
    cluster2xValue_dict = {}
    for xValue in xrange(len(unique_clusters)):
        cluster2xValue_dict[unique_clusters[xValue]] = xValue


    # 6B. Compute a list of labels for the clusters (in the same order as
    #     unique_clusters)
    unique_cluster_labels = [ fn_get_cluster_label(cluster)
                              for cluster in unique_clusters ]


    # 6C. Allocate a color for bar graphs of each major group
    colors = ('y', 'g', 'c', 'r', 'm', 'b')
    majorgroup2color_dict = {}
    for index, majorgroup in enumerate(unique_majorgroups):
        majorgroup2color_dict[majorgroup] = colors[index % len(colors)]


    # 7. For each unique subplot,
    #    For each unique majorgroup,
    #    For each unique cluster:
    #        Create an individual datapoints list
    #        Create a list of experiment directories
    datapoints_dict = {}
    clusterdir_dict = {}
    for subplot in unique_subplots:
        datapoints_dict[subplot] = {}
        clusterdir_dict[subplot] = {}
        for majorgroup in unique_majorgroups:
            datapoints_dict[subplot][majorgroup] = {}
            clusterdir_dict[subplot][majorgroup] = {}
            for cluster in unique_clusters:
                datapoints_dict[subplot][majorgroup][cluster] = []
                clusterdir_dict[subplot][majorgroup][cluster] = []


    # 8. Visit each directory and populate the corresponding datapoints list for
    #    that directory. Also populate the directory in the clusterdir_dict.
    for directory, prop_vals in dir2props_dict.iteritems():
        # Find the subplot, majorgroup, and cluster of the directory
        subplot = onlyIncludeProps(prop_vals, subplot_props)
        majorgroup = removeIgnoredProps(
                prop_vals, subplot_props + cluster_props + trial_props)
        cluster = onlyIncludeProps(prop_vals, cluster_props)

        # Compute the datapoint for the directory
        datapoint = fn_get_datapoint(directory)

        # Add the data point
        datapoints_dict[subplot][majorgroup][cluster].append(datapoint)

        # Add directory to the clusterdir_dict
        clusterdir_dict[subplot][majorgroup][cluster].append(directory)


    # 9. For each (subplot, majorgroup) combo, create a bar graph
    all_bars_dict = {}
    for subplot, subplot_dict in datapoints_dict.iteritems():
        all_bars_dict[subplot] = {}

        for majorgroup, majorgroup_dict in subplot_dict.iteritems():
            majorgroup_label = fn_get_majorgroup_label(majorgroup, common_props)

            bar = barGraph([], [], [], color=majorgroup2color_dict[majorgroup],
                           label=majorgroup_label)
            all_bars_dict[subplot][majorgroup] = bar


    # 10. Compute average and stddev for each (subplot, majorgroup, cluster)
    #     combination. This represents the avg and stddev across multiple
    #     trials. Add these to the corresponding bar graphs.
    for subplot, subplot_dict in datapoints_dict.iteritems():
        for majorgroup, majorgroup_dict in subplot_dict.iteritems():
            bar_values = []
            for cluster, datapoints in majorgroup_dict.iteritems():
                avg = numpy.average(datapoints)
                stddev = numpy.std(datapoints)

                # Append an (xValue, yValue, yError) tuple
                bar_values.append((cluster2xValue_dict[cluster], avg, stddev))

            # Sort the tuples by xValue and assign it to the bar graph.
            # (Boomslang requires the values to be sorted)
            bar = all_bars_dict[subplot][majorgroup]
            bar_values.sort(key=lambda tup: tup[0])
            # Unzip bar_values into individual lists
            (bar.xValues, bar.yValues, bar.yErrors) = zip(*bar_values)


    # 11. Create a clusteredBars Plot for each subplot.
    #     Place all the Plots in a single PlotLayout
    if not layout:
        layout = boomslang.PlotLayout()
    for subplot in unique_subplots:
        title = fn_get_subplot_title(subplot)

        subplot_bars = [ all_bars_dict[subplot][majorgroup]
                         for majorgroup in unique_majorgroups ]

        clusteredBars = clusteredBarsGraph(subplot_bars, unique_cluster_labels)

        plot = boomslang.Plot()

        # Add the clusteredbars for the particular subplot
        plot.add(clusteredBars)

        # Set title and axes labels
        plot.setXLabel(xLabel)
        plot.setYLabel(yLabel)
        plot.setTitle(title)
        plot.hasLegend()

        # Font size
        plot.setLegendLabelSize("small")
        plot.setTitleSize("small")
        plot.setAxesLabelSize("small")
        plot.setXTickLabelSize("small")
        plot.setYTickLabelSize("small")

        # Grid
        plot.grid.color = "lightgray"
        plot.grid.style = "dotted"
        plot.grid.lineWidth = 0.8
        plot.grid.visible = True

        # Add the plot to the layout
        layout.addPlot(plot, grouping=title)


    # 12. Update the clusterdir_dict to be index by subplot title, majorgroup
    # labels, and cluster labels.
    unique_subplot_titles = [ fn_get_subplot_title(subplot)
                              for subplot in unique_subplots ]
    unique_majorgroup_labels = [ fn_get_majorgroup_label(majorgroup,
                                                         common_props)
                                 for majorgroup in unique_majorgroups ]

    label_clusterdir_dict = {}
    for i, subplot in enumerate(unique_subplots):
        s_title = unique_subplot_titles[i]
        label_clusterdir_dict[s_title] = {}

        for j, majorgroup in enumerate(unique_majorgroups):
            m_label = unique_majorgroup_labels[j]
            label_clusterdir_dict[s_title][m_label] = {}

            for k, cluster in enumerate(unique_clusters):
                c_label = unique_cluster_labels[k]
                label_clusterdir_dict[s_title][m_label][c_label] = (
                        clusterdir_dict[subplot][majorgroup][cluster])


    # 13. Set the order of subplots in the layout
    layout.setGroupOrder(unique_subplot_titles)


    # 14. Return the final PlotLayout and other results
    return (unique_subplot_titles, unique_majorgroup_labels,
            unique_cluster_labels, label_clusterdir_dict, layout)


# Returns the comparison of mcperf latency summaries. Each experiment's latency
# distribution is reduced to a single datapoint, Eg. avg, pc99, pc999 etc.
def plotLineComparisonDirs(dir2props_dict, # dict
                           xgroup_props,   # list. Props to group along x axis
                           line_props,     # list. Properties of line
                           fn_sort_lines,
                           fn_get_line_label,
                           fn_get_xgroup_value,  # xValue. No separate label
                           fn_get_datapoint,     # yValue
                           xLabel,
                           yLabel,
                           title,
                           xLimits = None,
                           yLimits = None,
                           for_paper = False):

    # 1. Turn each directory's set of prop=val strings into a dictionary to
    #     easily look up the value of a particular property for the directory
    dir2prop2val_dict = getDir2Prop2ValDict(dir2props_dict)


    # 2. Find all the common and unique properties among all directories
    common_props, unique_props = getCommonAndUniqueProperties(dir2props_dict)


    # 3A. Find all unique values of line properties (each is separate line)
    line2dir_dict = getDirGroupsByProperty(dir2props_dict, line_props,
                                           ignore = False)
    unique_lines = line2dir_dict.keys()
    # 3B. Sort the lines
    fn_sort_lines(unique_lines)


    # 4. Find all unique values of the xgroup properties
    xgroup2dir_dict = getDirGroupsByProperty(dir2props_dict, xgroup_props,
                                             ignore = False)
    unique_xgroups = xgroup2dir_dict.keys()


    # 5. For each unique line,
    #    For each unique xgroup,
    #        Create an individual datapoints list
    datapoints_dict = {}
    for line in unique_lines:
        datapoints_dict[line] = {}
        for xgroup in unique_xgroups:
            datapoints_dict[line][xgroup] = []


    # 6. Visit each directory and populate the corresponding datapoints list for
    #    that directory.
    for directory, prop_vals in dir2props_dict.iteritems():
        # Find the line and xgroup of the directory
        line = onlyIncludeProps(prop_vals, line_props)
        xgroup = onlyIncludeProps(prop_vals, xgroup_props)

        # Compute the datapoint for the directory
        datapoint = fn_get_datapoint(directory)

        # Add the data point
        datapoints_dict[line][xgroup].append(datapoint)


    # 7. For each unique line prop, create a line.
    #    Set the label and color for the line
    colors = ('b', 'g', 'r', 'm', 'c', 'y')
    all_lines_dict = {}
    for index, line in enumerate(unique_lines):
        l = boomslang.Line()
        l.color = colors[index % len(colors)]
        l.label = fn_get_line_label(line)
        l.width = 2
        l.marker = 'o'
        all_lines_dict[line] = l


    # 8. Compute average and stddev for each (line, xgroup) combination. This
    #    represents the avg and stddev across multiple trials.
    #    Add these to the corresponding lines.
    for line, line_dict in datapoints_dict.iteritems():
        for xgroup, datapoints in line_dict.iteritems():
            avg = numpy.average(datapoints)
            stddev = numpy.std(datapoints)

            # Append xValue, yValue, yError to the line
            xValue = fn_get_xgroup_value(xgroup)
            all_lines_dict[line].xValues.append(xValue)
            all_lines_dict[line].yValues.append(avg)
            all_lines_dict[line].yErrors.append(stddev)


    # 9. Create the plot and add all the lines
    plot = boomslang.Plot()
    for line in unique_lines:
        plot.add(all_lines_dict[line])

    # 9A. Set title and axes labels
    plot.setXLabel(xLabel)
    plot.setYLabel(yLabel)
    plot.setTitle(title)
    plot.hasLegend()

    # 9B. Font size
    plot.setLegendLabelSize("small")
    plot.setTitleSize("small")
    plot.setAxesLabelSize("small")
    plot.setXTickLabelSize("small")
    plot.setYTickLabelSize("small")

    # 9C. Grid
    plot.grid.color = "lightgray"
    plot.grid.style = "dotted"
    plot.grid.lineWidth = 0.8
    plot.grid.visible = True

    # 9D. xLimits, yLimits
    if xLimits:
        plot.xLimits = xLimits
    if yLimits:
        plot.yLimits = yLimits


    # 10. Set dimensions of the plot
    if for_paper:
        plot.setDimensions(width=4.5)


    # 11. Return the plot
    return plot


###############################################################
# Additional utility functions for plotting comparison graphs #
###############################################################


def getRateMbpsFromPropValSet(rate_val_set):
    # The rate_mbps=value string should be the only element in the set
    rate_dict = getPropsDict(rate_val_set)
    return int(rate_dict['rate_mbps'])


def getNClassesFromPropValSet(nclasses_val_set):
    # The nclasses=value string should be the only element in the set
    nclasses_dict = getPropsDict(nclasses_val_set)
    return int(nclasses_dict['nclasses'])


def sortRateValSets(rate_val_sets):
    rate_val_sets.sort(key = lambda rate_val_set:
                       getRateMbpsFromPropValSet(rate_val_set)),


def sortNClassesValSets(nclasses_val_sets):
    nclasses_val_sets.sort(key = lambda nclasses_val_set:
                           getNClassesFromPropValSet(nclasses_val_set)),


def getSysConfLabel(sysconf, common_props):
    sysconf_label_props = ((sysconf - common_props) |
                           onlyIncludeProps(sysconf, 'rl'))
    return ', '.join(sorted(sysconf_label_props))
