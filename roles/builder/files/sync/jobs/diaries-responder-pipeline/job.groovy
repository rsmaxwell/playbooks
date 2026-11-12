multibranchPipelineJob('diaries-responder-pipeline') {
    branchSources {
        git {
            id = 'diaries-responder-pipeline'
            remote('https://github.com/rsmaxwell/diaries-responder-pipeline.git')
        }
    }
}
